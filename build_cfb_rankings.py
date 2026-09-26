#!/usr/bin/env python3
"""
Per-team AP poll trajectory for 2026 (CFBD /rankings).

A team's ranking movement is the cleanest human-readable "is the preseason prior stale?"
signal: Oklahoma going AP #10 -> #11 -> #24 -> unranked means the model's SP+ prior (set
when they were #10) is propping up a team that has since collapsed. Surfacing the
trajectory lets the card -- and the reader -- discount a number that leans on a dead rank.

Output: data/scenarios/cfb_rankings.json
  { season, updated, teams: {school: {open, now, peak, weeks:{wk:rank}, trend, fell_out}} }
"""
from __future__ import annotations
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from fetch_game_lines import load_local_env

BASE_DIR = Path(__file__).resolve().parent
OUT_PATH = BASE_DIR / "data" / "scenarios" / "cfb_rankings.json"
POLL = "AP Top 25"


def build(season: int) -> dict:
    key = os.getenv("CFBD_API_KEY")
    if not key:
        raise SystemExit("No CFBD_API_KEY in environment or .env(.local)")
    req = urllib.request.Request(
        f"https://api.collegefootballdata.com/rankings?year={season}&seasonType=regular",
        headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)

    per = {}  # school -> {week: rank}
    weeks_seen = set()
    for wk in data:
        w = wk.get("week")
        weeks_seen.add(w)
        for poll in wk.get("polls", []):
            if poll.get("poll") != POLL:
                continue
            for rnk in poll.get("ranks", []):
                per.setdefault(rnk["school"], {})[w] = rnk.get("rank")

    last_week = max(weeks_seen) if weeks_seen else None
    teams = {}
    for school, wkmap in per.items():
        ws = sorted(wkmap)
        open_rank = wkmap[ws[0]]
        peak = min(wkmap.values())
        now = wkmap.get(last_week)  # None if not ranked in the latest poll
        fell_out = now is None
        if fell_out:
            trend = "fell out"
        elif now < open_rank:
            trend = "rising"
        elif now > open_rank:
            trend = "falling"
        else:
            trend = "steady"
        teams[school] = {
            "open": open_rank, "now": now, "peak": peak,
            "weeks": {str(w): wkmap[w] for w in ws},
            "trend": trend, "fell_out": fell_out,
            "last_ranked_week": (max(wkmap) if fell_out else last_week),
        }
    return {"season": season,
            "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "last_poll_week": last_week, "teams": teams}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    args = ap.parse_args()
    load_local_env(BASE_DIR)
    data = build(args.season)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    fo = sum(1 for t in data["teams"].values() if t["fell_out"])
    print(f"Wrote AP trajectory for {len(data['teams'])} teams ({fo} fallen out) -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
