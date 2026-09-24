#!/usr/bin/env python3
"""
NFL injury context for the matchup read.

The form engine reasons off box scores, which are a rearview: they can't see that a
team's #1 corner is on IR this week, or that a key receiver is out tonight. This joins
the live injury feed (data/injuries/NFL_Injuries.csv) to positions (the current roster)
so the matchup card can surface the availability that actually moves props and totals --
ranked by how much a position matters to a game read, not just dumped alphabetically.

Honest and non-fabricating: it reports STATUS as posted (OUT / DOUBTFUL / QUESTIONABLE)
and never invents an impact magnitude. Degrades to empty if a feed is missing.
"""
from __future__ import annotations
import csv
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INJ_PATH = BASE_DIR / "data" / "injuries" / "NFL_Injuries.csv"
ROSTER_PATH = BASE_DIR / "data" / "rosters" / "NFL_CurrentRoster.csv"

# How much a position moves a prop/total read (higher = surface first).
POS_PRIORITY = {
    "QB": 100,
    "WR": 80, "RB": 78, "TE": 70,
    "CB": 60, "S": 55, "DB": 55, "EDGE": 58, "DE": 56, "OLB": 52, "LB": 50, "DT": 46,
    "OT": 44, "T": 44, "G": 40, "C": 40, "OL": 40,
    "K": 20, "PK": 20, "P": 10,
}
STATUS_RANK = {"OUT": 3, "DOUBTFUL": 2, "QUESTIONABLE": 1}
# Below this priority we only surface hard OUT/DOUBTFUL, not QUESTIONABLE (cut O-line
# tweaks and depth QUESTIONABLEs that don't move a card).
Q_MIN_PRIORITY = 60


def _norm(s) -> str:
    return str(s or "").strip().lower()


@lru_cache(maxsize=1)
def _positions() -> dict:
    """(player_norm, team) -> position, from the current roster."""
    out = {}
    if not ROSTER_PATH.exists():
        return out
    try:
        with ROSTER_PATH.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                out[(_norm(r.get("Player")), str(r.get("CurrentTeam") or "").strip().upper())] = \
                    str(r.get("Position") or "").strip().upper()
    except Exception:
        return {}
    return out


@lru_cache(maxsize=1)
def _rows() -> tuple:
    if not INJ_PATH.exists():
        return tuple()
    try:
        with INJ_PATH.open(encoding="utf-8") as fh:
            return tuple(dict(r) for r in csv.DictReader(fh))
    except Exception:
        return tuple()


def clear_cache():
    _rows.cache_clear()
    _positions.cache_clear()


def _short_reason(reason: str) -> str:
    """Pull the ailment in parens ('(hamstring)') or the leading clause; keep it short."""
    r = str(reason or "").strip()
    if "(" in r and ")" in r:
        return r[r.find("(") + 1:r.find(")")]
    return ""


def team_injuries(team_abbr: str, limit: int = 6) -> list:
    """Prioritized injuries for a team: OUT/DOUBTFUL always, QUESTIONABLE only for
    high-impact positions. Each: {player, pos, status, ailment, priority}."""
    ab = str(team_abbr or "").strip().upper()
    pos = _positions()
    out = []
    for r in _rows():
        if str(r.get("Team") or "").strip().upper() != ab:
            continue
        status = str(r.get("Status") or "").strip().upper()
        if status not in STATUS_RANK:
            continue
        player = str(r.get("Player") or "").strip()
        p = pos.get((_norm(player), ab), "")
        pr = POS_PRIORITY.get(p, 30)
        if status == "QUESTIONABLE" and pr < Q_MIN_PRIORITY:
            continue
        out.append({
            "player": player, "pos": p or "?", "status": status,
            "ailment": _short_reason(r.get("Reason")), "priority": pr,
            "_sort": (STATUS_RANK[status], pr),
        })
    out.sort(key=lambda x: x["_sort"], reverse=True)
    for o in out:
        o.pop("_sort", None)
    return out[:limit]


def injury_note(team_abbr: str, limit: int = 4) -> str | None:
    """One-line summary of a team's availability that matters to the card."""
    inj = team_injuries(team_abbr, limit=limit)
    if not inj:
        return None
    parts = []
    for i in inj:
        tag = {"OUT": "OUT", "DOUBTFUL": "DOUBT", "QUESTIONABLE": "Q"}[i["status"]]
        ail = f" ({i['ailment']})" if i["ailment"] else ""
        parts.append(f"{i['player']} [{i['pos']}] {tag}{ail}")
    return f"{str(team_abbr).upper()} injuries: " + "; ".join(parts)


if __name__ == "__main__":
    import sys
    for t in (sys.argv[1:] or ["ATL", "GB"]):
        print(injury_note(t) or f"{t}: no notable injuries")
