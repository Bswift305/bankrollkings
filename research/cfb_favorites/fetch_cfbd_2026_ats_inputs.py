# -*- coding: utf-8 -*-
"""
Append the CURRENT-season (2026) rows to the ATS-export input CSVs so
build_cfb_ats_export.py folds this season into the cover-rate data. Idempotent:
strips any existing rows for --year and re-appends fresh, so it can run weekly.

Pulls completed games, consensus lines, and coach-season records from CFBD, in the
exact schemas the three CSVs already use. Needs CFBD_API_KEY in the env / .env.local.

    python research/cfb_favorites/fetch_cfbd_2026_ats_inputs.py --year 2026
"""
import argparse
import csv
import json
import os
import pathlib
from collections import defaultdict
from statistics import mean
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = pathlib.Path(__file__).resolve().parents[2]
H = ROOT / "data" / "historical"
GAMES = H / "CFBD_Games_2016_2025.csv"
LINES = H / "CFBD_Lines_2016_2025.csv"
COACHES = H / "CFBD_Coaches_2016_2025.csv"
BASE = "https://api.collegefootballdata.com"


def _key():
    k = os.getenv("CFBD_API_KEY") or os.getenv("COLLEGEFOOTBALLDATA_API_KEY")
    if not k:
        env = ROOT / ".env.local"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("CFBD_API_KEY="):
                    k = line.split("=", 1)[1].strip()
                    break
    if not k:
        raise SystemExit("Missing CFBD_API_KEY.")
    return k.strip()


def _get(path, key, **params):
    url = f"{BASE}{path}?{urlencode({k: v for k, v in params.items() if v})}"
    req = Request(url, headers={"Authorization": f"Bearer {key}", "Accept": "application/json",
                               "User-Agent": "BankrollKings/1.0"})
    with urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _rewrite_without_year(path, year, fieldnames, year_col):
    """Drop existing rows for `year` so re-running refreshes cleanly."""
    yr = str(year)
    kept = []
    if path.exists():
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if str(row.get(year_col, "")).strip() != yr:
                    kept.append(row)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(kept)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2026)
    args = ap.parse_args()
    year = args.year
    key = _key()

    # ---- games (completed only) ----
    games = _get("/games", key, year=year, seasonType="regular")
    game_rows = []
    for g in games:
        hp = g.get("homePoints", g.get("home_points"))
        ap_ = g.get("awayPoints", g.get("away_points"))
        if hp is None or ap_ is None:
            continue  # not yet played
        game_rows.append({
            "id": g.get("id", ""), "season": g.get("season", year), "week": g.get("week", ""),
            "homeTeam": g.get("homeTeam", g.get("home_team", "")),
            "awayTeam": g.get("awayTeam", g.get("away_team", "")),
            "homeConf": g.get("homeConference", g.get("home_conference", "")) or "",
            "awayConf": g.get("awayConference", g.get("away_conference", "")) or "",
            "homePts": int(hp), "awayPts": int(ap_),
            "neutral": g.get("neutralSite", g.get("neutral_site", "")),
        })

    # ---- lines (consensus spread/total across books) ----
    lines = _get("/lines", key, year=year, seasonType="regular")
    line_rows = []
    for item in lines:
        provs = item.get("lines") or []
        spreads = [_num(p.get("spread")) for p in provs]
        totals = [_num(p.get("overUnder") or p.get("total")) for p in provs]
        spreads = [s for s in spreads if s is not None]
        totals = [t for t in totals if t is not None]
        if not spreads:
            continue
        line_rows.append({
            "season": item.get("season", year), "week": item.get("week", ""),
            "homeTeam": item.get("homeTeam", item.get("home_team", "")),
            "awayTeam": item.get("awayTeam", item.get("away_team", "")),
            "spread": round(mean(spreads), 1),
            "total": round(mean(totals), 1) if totals else "",
            "books": len(provs),
        })

    # ---- coaches (this season's school + games) ----
    coaches = _get("/coaches", key, year=year)
    coach_rows = []
    for c in coaches:
        name = (str(c.get("firstName", "")).strip() + " " + str(c.get("lastName", "")).strip()).strip()
        for s in (c.get("seasons") or []):
            if str(s.get("year")) != str(year):
                continue
            coach_rows.append({
                "coach": name, "school": s.get("school", ""), "year": s.get("year", year),
                "games": s.get("games", 0), "wins": s.get("wins", 0), "losses": s.get("losses", 0),
            })

    _rewrite_without_year(GAMES, year, ["id", "season", "week", "homeTeam", "awayTeam", "homeConf", "awayConf", "homePts", "awayPts", "neutral"], "season")
    _rewrite_without_year(LINES, year, ["season", "week", "homeTeam", "awayTeam", "spread", "total", "books"], "season")
    _rewrite_without_year(COACHES, year, ["coach", "school", "year", "games", "wins", "losses"], "year")

    with open(GAMES, "a", newline="", encoding="utf-8") as fh:
        csv.DictWriter(fh, fieldnames=["id", "season", "week", "homeTeam", "awayTeam", "homeConf", "awayConf", "homePts", "awayPts", "neutral"]).writerows(game_rows)
    with open(LINES, "a", newline="", encoding="utf-8") as fh:
        csv.DictWriter(fh, fieldnames=["season", "week", "homeTeam", "awayTeam", "spread", "total", "books"]).writerows(line_rows)
    with open(COACHES, "a", newline="", encoding="utf-8") as fh:
        csv.DictWriter(fh, fieldnames=["coach", "school", "year", "games", "wins", "losses"]).writerows(coach_rows)

    print(f"{year}: appended {len(game_rows)} games, {len(line_rows)} lines, {len(coach_rows)} coach rows")


if __name__ == "__main__":
    main()
