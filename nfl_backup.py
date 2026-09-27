#!/usr/bin/env python3
"""
Backup-QB-weighted injury impact.

When a team's starting QB is out, the prop and total impact depends on WHO replaces him.
A flat "fade the receivers" is wrong for a gunslinger backup (Jameis Winston: ~30 att/gm,
3.9% INT -> WR volume holds, turnover variance) and too soft for a game-manager (Marcus
Mariota: 20 att/gm -> receivers crater, run-heavy). This finds the backup (roster QB minus
the injured starter), classifies him from his profile, and returns a scaled impact:
a total-model penalty plus tailored WR / RB / QB read.

Data: data/scenarios/nfl_qb_profiles.json (build_nfl_qb_profiles.py),
      data/rosters/NFL_CurrentRoster.csv, and nfl_totals for the out-QB detector.
"""
from __future__ import annotations
import csv
import json
import re
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROFILE_PATH = BASE_DIR / "data" / "scenarios" / "nfl_qb_profiles.json"
ROSTER_PATH = BASE_DIR / "data" / "rosters" / "NFL_CurrentRoster.csv"
LEAGUE_ATT = 33.0  # ~ a full-time starter's attempts/game
_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\.?$", re.I)


def _nm(s):
    n = _SUFFIX.sub("", str(s or "").strip().lower()).strip()
    return re.sub(r"[^a-z ]", "", n).strip()


@lru_cache(maxsize=1)
def _profiles() -> dict:
    if not PROFILE_PATH.exists():
        return {}
    try:
        return {_nm(k): v for k, v in json.loads(PROFILE_PATH.read_text(encoding="utf-8")).get("qbs", {}).items()}
    except Exception:
        return {}


@lru_cache(maxsize=1)
def _roster_qbs() -> dict:
    """team_abbr -> [player names] for QBs on the current roster."""
    from collections import defaultdict
    out = defaultdict(list)
    if not ROSTER_PATH.exists():
        return {}
    try:
        with ROSTER_PATH.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if str(r.get("Position", "")).strip().upper() == "QB":
                    out[str(r.get("CurrentTeam", "")).strip().upper()].append(str(r.get("Player", "")).strip())
    except Exception:
        return {}
    return dict(out)


def clear_cache():
    _profiles.cache_clear()
    _roster_qbs.cache_clear()


def backup_for(team: str, out_qb: str):
    """The likely starter with `out_qb` sidelined: the rostered QB (not the injured one)
    with the richest profile. Returns (name, profile) or (None, None)."""
    profs = _profiles()
    cands = [q for q in _roster_qbs().get(str(team).upper(), []) if _nm(q) != _nm(out_qb)]
    best = None
    for q in cands:
        p = profs.get(_nm(q))
        if p and (best is None or p["games"] > best[1]["games"]):
            best = (q, p)
    return best if best else (None, None)


def impact(team: str) -> dict | None:
    """Backup-weighted impact for a team whose starting QB is out. None if QB not out."""
    try:
        import nfl_totals as _nt
        out_qb = _nt.qb_out(team)
    except Exception:
        out_qb = None
    if not out_qb:
        return None
    backup, p = backup_for(team, out_qb)
    if not p:  # unknown/deep backup -> assume a weak game-manager
        return {"out_qb": out_qb, "backup": backup or "a backup", "style": "unproven",
                "total_penalty": 8.0,
                "wr": {"dir": "down", "note": "unproven backup — receivers downgrade, fade"},
                "rb": {"dir": "up", "note": "run-heavier to shield an unproven QB — volume up"},
                "qb": {"dir": "backup", "note": "unproven backup — volatile, low volume"}}
    att, ypa, intr, rush = p["att_pg"], p["ypa"], p["int_rate"], p["rush_pg"]
    tag = []
    if intr >= 3.2:
        tag.append("gunslinger")
    if rush >= 5:
        tag.append("dual-threat")
    if att < 26:
        tag.append("game-manager")
    style = "/".join(tag) or "starter-caliber"

    if att >= 29:  # keeps passing volume near a starter's -> receivers hold
        turn = f", turnover-prone ({intr}% INT)" if intr >= 3 else ""
        wr = {"dir": "hold", "note": f"{backup} keeps volume up ({att} att/gm{turn}) — coin flip, not a fade"}
        rb = {"dir": "up" if intr >= 3 else "hold",
              "note": "checkdown/pressure volume up" if intr >= 3 else "volume roughly steady"}
        pen = 4.5 if ypa >= 6.8 else 6.0
    elif att < 25:  # low-volume game-manager -> receivers crater
        wr = {"dir": "down", "note": f"{backup} throws little ({att} att/gm) — clear downgrade, fade"}
        rb = {"dir": "up", "note": "run-heavy to protect the game-manager — volume up"}
        pen = 7.5
    else:  # moderate
        wr = {"dir": "down", "note": f"{backup} ({att} att/gm) — receivers downgrade"}
        rb = {"dir": "up", "note": "run game leans up"}
        pen = 6.0
    qb = {"dir": "backup",
          "note": f"{backup}: {att} att/gm, {ypa} YPA, {intr}% INT" + (f", {rush} rush/gm" if rush >= 5 else "")}
    return {"out_qb": out_qb, "backup": backup, "style": style,
            "total_penalty": round(pen, 1), "wr": wr, "rb": rb, "qb": qb}


if __name__ == "__main__":
    import sys
    for t in (sys.argv[1:] or ["WAS", "NYG"]):
        print(t, "->", json.dumps(impact(t), indent=2) if impact(t) else "QB not out")
