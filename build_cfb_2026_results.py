#!/usr/bin/env python3
"""
Build the current-season (2026) CFB results file that powers the current-form /
common-opponent read. Fetches every completed FBS game from CFBD in one call.

Why: the CFB tools were leaning on prior-season ATS trends (cfb_ats.json) and
missing how teams have actually played THIS year. This gives the site current
form + common-opponent comparisons (e.g. Houston beat Oregon State by 13, Texas
Tech beat them by 11 -> the two are close, so a -7.5 line is ~fair).

Run weekly in-season. Needs CFBD_API_KEY. Output: data/scenarios/cfb_2026_results.json
"""
from __future__ import annotations
import argparse
import json
import os
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUT_PATH = BASE_DIR / "data" / "scenarios" / "cfb_2026_results.json"


def fetch(season: int) -> list[dict]:
    key = os.environ.get("CFBD_API_KEY", "")
    if not key:
        raise SystemExit("CFBD_API_KEY not set")
    url = f"https://api.collegefootballdata.com/games?year={season}&seasonType=regular"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    data = json.load(urllib.request.urlopen(req, timeout=60))
    rows = []
    for g in data:
        hp, ap = g.get("homePoints"), g.get("awayPoints")
        if not g.get("completed") or hp is None or ap is None:
            continue
        rows.append({
            "week": g.get("week"),
            "home": g.get("homeTeam"), "away": g.get("awayTeam"),
            "home_pts": hp, "away_pts": ap,
            "neutral": bool(g.get("neutralSite")),
            "home_elo": g.get("homePregameElo"), "away_elo": g.get("awayPregameElo"),
            "home_conf": g.get("homeConference"), "away_conf": g.get("awayConference"),
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    args = ap.parse_args()
    rows = fetch(args.season)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({"season": args.season, "games": rows}), encoding="utf-8")
    print(f"Wrote {len(rows)} completed {args.season} games -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
