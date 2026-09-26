#!/usr/bin/env python3
"""
Capture CFB line movement (open -> current) from CFBD.

The game-line feeds only stored the CURRENT number, so we couldn't answer "Georgia
opened -10, why is it -13.5 now?" without reconstructing it by hand. CFBD's /lines
endpoint returns BOTH the opening and current spread/total per game, so this records
consensus open vs current for every game with a line and writes a small, committable
movement file the CFB matchup card reads.

Movement is CONTEXT, not an edge -- our own research says steam/line-chasing is already
priced. It just makes the number's history readily handy instead of a live lookup.

Output: data/scenarios/cfb_line_moves.json. Run in the CFB refresh lane.
"""
from __future__ import annotations
import json
import os
import statistics
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from fetch_game_lines import load_local_env

BASE_DIR = Path(__file__).resolve().parent
OUT_PATH = BASE_DIR / "data" / "scenarios" / "cfb_line_moves.json"


def _median(vals):
    vals = [v for v in vals if v is not None]
    return round(statistics.median(vals), 1) if vals else None


def build(season: int) -> dict:
    key = os.getenv("CFBD_API_KEY")
    if not key:
        raise SystemExit("No CFBD_API_KEY in environment or .env(.local)")
    url = f"https://api.collegefootballdata.com/lines?year={season}&seasonType=regular"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)

    games = []
    for g in data:
        lines = g.get("lines") or []
        if not lines:
            continue
        sp_now = _median([l.get("spread") for l in lines])            # home perspective
        sp_open = _median([l.get("spreadOpen") for l in lines])
        tot_now = _median([l.get("overUnder") for l in lines])
        tot_open = _median([l.get("overUnderOpen") for l in lines])
        if sp_now is None and tot_now is None:
            continue
        rec = {
            "week": g.get("week"), "home": g.get("homeTeam"), "away": g.get("awayTeam"),
            "completed": g.get("homeScore") is not None,
            "spread_open": sp_open, "spread_now": sp_now,
            "spread_move": (round(sp_now - sp_open, 1) if (sp_now is not None and sp_open is not None) else None),
            "total_open": tot_open, "total_now": tot_now,
            "total_move": (round(tot_now - tot_open, 1) if (tot_now is not None and tot_open is not None) else None),
            "books": len(lines),
        }
        games.append(rec)

    return {
        "season": season,
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "n_games": len(games),
        "games": games,
    }


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    args = ap.parse_args()
    load_local_env(BASE_DIR)
    data = build(args.season)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    moved = sum(1 for g in data["games"] if g.get("spread_move"))
    print(f"Wrote {data['n_games']} games ({moved} with spread movement) -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
