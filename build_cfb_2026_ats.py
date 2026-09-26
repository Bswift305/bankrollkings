#!/usr/bin/env python3
"""
Per-team CURRENT-SEASON (2026) ATS cover record from CFBD lines.

The multi-year coach/team ATS history is a prior that can CONFLICT with how a team is
playing THIS year -- e.g. a coach who historically pulled starters and didn't cover big,
but is now 3-0 ATS and burying teams. When they diverge, recency wins, so the matchup
card must show this season's ATS record and lead with it. This computes it from CFBD
lines (consensus current spread) + final scores.

Output: data/scenarios/cfb_2026_ats.json  { season, teams: {school: {ats, cover, acm, n}} }
"""
from __future__ import annotations
import json
import os
import statistics
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from fetch_game_lines import load_local_env

BASE_DIR = Path(__file__).resolve().parent
OUT_PATH = BASE_DIR / "data" / "scenarios" / "cfb_2026_ats.json"


def build(season: int) -> dict:
    key = os.getenv("CFBD_API_KEY")
    if not key:
        raise SystemExit("No CFBD_API_KEY in environment or .env(.local)")
    req = urllib.request.Request(
        f"https://api.collegefootballdata.com/lines?year={season}&seasonType=regular",
        headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)

    rec = defaultdict(lambda: {"c": 0, "l": 0, "p": 0, "acm": []})
    for g in data:
        if g.get("homeScore") is None or not g.get("lines"):
            continue
        sp = [l["spread"] for l in g["lines"] if l.get("spread") is not None]
        if not sp:
            continue
        spread = statistics.median(sp)  # home perspective, negative = home favored
        h, a = g["homeTeam"], g["awayTeam"]
        cov = (g["homeScore"] - g["awayScore"]) + spread  # >0 home covers
        for team, margin in ((h, cov), (a, -cov)):
            r_ = rec[team]
            r_["acm"].append(margin)
            if margin > 0.001:
                r_["c"] += 1
            elif margin < -0.001:
                r_["l"] += 1
            else:
                r_["p"] += 1

    teams = {}
    for t, r_ in rec.items():
        n = r_["c"] + r_["l"]
        if n == 0:
            continue
        teams[t] = {
            "ats": f"{r_['c']}-{r_['l']}" + (f"-{r_['p']}" if r_["p"] else ""),
            "cover": round(100 * r_["c"] / n),
            "acm": round(sum(r_["acm"]) / len(r_["acm"]), 1),  # avg cover margin vs the line
            "n": n,
        }
    return {"season": season,
            "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "teams": teams}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    args = ap.parse_args()
    load_local_env(BASE_DIR)
    data = build(args.season)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Wrote 2026 ATS for {len(data['teams'])} teams -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
