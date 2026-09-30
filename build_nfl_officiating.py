#!/usr/bin/env python3
"""Build NFL officiating tendencies + this week's crew assignments from nflverse games.csv.

For every referee, from completed games (2019+), compute the totals lean (how often his
games go OVER the closing total), the average total points, home straight-up record, and
sample size -- the bettable officiating angle (penalty-driven scoring shows up in the O/U
record; games.csv has no penalty counts). Then attach each ref's profile to this week's
assigned-but-unplayed games.

Writes data/scenarios/nfl_officiating.json. Wire into run_daily.py (needs a network pull
of games.csv, like build_nfl_scores). Honest: ref O/U leans sit near the 49% league
baseline -- context and a small edge at best, not a system.
"""
from __future__ import annotations

import io
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
OUT_PATH = BASE_DIR / "data" / "scenarios" / "nfl_officiating.json"
GAMES_URL = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"
_UA = {"User-Agent": "Mozilla/5.0"}
_ALIAS = {"Ronald Torbert": "Ron Torbert"}   # nflverse name variants
SINCE = 2019
MIN_GAMES = 20


def _lean(over_pct):
    if over_pct is None:
        return "Neutral"
    if over_pct >= 53:
        return "Over-leaning"
    if over_pct <= 46:
        return "Under-leaning"
    return "Neutral"


def main() -> int:
    try:
        raw = urllib.request.urlopen(urllib.request.Request(GAMES_URL, headers=_UA), timeout=60).read().decode()
        g = pd.read_csv(io.StringIO(raw))
    except Exception as exc:
        print(f"[build_nfl_officiating] could not fetch games.csv: {exc}")
        return 1
    g["referee"] = g["referee"].map(lambda x: _ALIAS.get(str(x).strip(), str(x).strip()) if pd.notna(x) else x)
    g["season"] = pd.to_numeric(g["season"], errors="coerce")

    done = g[(g["referee"].notna()) & (g["result"].notna()) & (g["total"].notna())
             & (g["total_line"].notna()) & (g["season"] >= SINCE)].copy()
    tend = {}
    for ref, sub in done.groupby("referee"):
        n = int(len(sub))
        over = int((sub["total"] > sub["total_line"]).sum())
        under = int((sub["total"] < sub["total_line"]).sum())
        push = n - over - under
        homewin = int((sub["result"] > 0).sum())
        ou = over + under
        over_pct = round(100 * over / ou) if ou else None
        tend[ref] = {
            "n": n, "over": over, "under": under, "push": push,
            "over_pct": over_pct, "lean": _lean(over_pct),
            "avg_total": round(float(sub["total"].mean()), 1),
            "home_su_pct": round(100 * homewin / n) if n else None,
        }
    # league baseline for context
    base_ou = (done["total"] > done["total_line"]).sum() + (done["total"] < done["total_line"]).sum()
    baseline = {
        "n": int(len(done)),
        "over_pct": round(100 * (done["total"] > done["total_line"]).sum() / base_ou) if base_ou else None,
        "avg_total": round(float(done["total"].mean()), 1),
        "home_su_pct": round(100 * (done["result"] > 0).sum() / len(done)) if len(done) else None,
    }

    # this week's assignments = games with a ref but no result yet, nearest upcoming week
    upc = g[(g["referee"].notna()) & (g["result"].isna()) & (g["season"] == g["season"].max())].copy()
    upc["week"] = pd.to_numeric(upc["week"], errors="coerce")
    assignments = []
    if not upc.empty:
        wk = int(upc["week"].min())
        for _, r in upc[upc["week"] == wk].iterrows():
            ref = str(r["referee"]).strip()
            prof = tend.get(ref)
            assignments.append({
                "week": wk, "away": str(r["away_team"]), "home": str(r["home_team"]),
                "gameday": str(r.get("gameday") or ""), "referee": ref,
                "total_line": (float(r["total_line"]) if pd.notna(r.get("total_line")) else None),
                "profile": prof if (prof and prof["n"] >= MIN_GAMES) else None,
            })

    data = {
        "season": int(g["season"].max()),
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "since": SINCE, "min_games": MIN_GAMES,
        "baseline": baseline,
        "referees": {k: v for k, v in tend.items() if v["n"] >= MIN_GAMES},
        "assignments": assignments,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"[build_nfl_officiating] {len(data['referees'])} referee profiles, "
          f"{len(assignments)} assignments (wk {assignments[0]['week'] if assignments else '-'}) -> {OUT_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
