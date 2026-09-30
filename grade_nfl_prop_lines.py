#!/usr/bin/env python3
"""Grade the archived NFL prop lines against actual game results, for EVERY prop category.

Reads data/tracking/NFL_PropLines_Archive.csv (the daily line snapshots from
capture_nfl_prop_lines.py), joins each line to the player's real production that week
(nflverse weekly logs), and writes data/tracking/NFL_PropLines_Graded.csv with the actual
value + OVER/UNDER/PUSH/PENDING result. This is the running record behind the "tickets we
could have hit" scoreboard.

Uses the SAME stat registry as the floor engine (app._NFL_FLOOR_STATS / _NFL_PROP_STAT_MAP)
so computed stats (Anytime TD, Tackles+Assists, Rush+Rec) and defense all grade correctly.
Idempotent: re-grades the whole archive each run (cheap), so pending games resolve as
gamelogs fill in. Wire into run_daily.py after the prop-line capture + gamelog refresh.
"""
from __future__ import annotations

import io
import urllib.request
from pathlib import Path

import pandas as pd

from app import (_nfl_player_week_data, _nfl_name_key, _NFL_FLOOR_STATS, _NFL_PROP_STAT_MAP)

BASE_DIR = Path(__file__).resolve().parent
ARCHIVE = BASE_DIR / "data" / "tracking" / "NFL_PropLines_Archive.csv"
OUT = BASE_DIR / "data" / "tracking" / "NFL_PropLines_Graded.csv"
GAMES_URL = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"
_UA = {"User-Agent": "Mozilla/5.0"}


def _date_to_week() -> dict:
    """(season:int, 'YYYY-MM-DD') -> week, from nflverse games.csv."""
    out = {}
    try:
        raw = urllib.request.urlopen(urllib.request.Request(GAMES_URL, headers=_UA), timeout=60).read().decode()
        g = pd.read_csv(io.StringIO(raw))
        for _, r in g.iterrows():
            try:
                out[(int(r["season"]), str(r["gameday"])[:10])] = int(r["week"])
            except (TypeError, ValueError):
                continue
    except Exception as exc:
        print(f"[grade_nfl_prop_lines] could not fetch games.csv ({exc}); week join limited")
    return out


def main() -> int:
    if not ARCHIVE.exists():
        print("[grade_nfl_prop_lines] no archive yet; nothing to grade")
        return 0
    arc = pd.read_csv(ARCHIVE)
    if arc.empty:
        print("[grade_nfl_prop_lines] archive empty")
        return 0
    log = _nfl_player_week_data()
    if log.empty:
        print("[grade_nfl_prop_lines] no player logs")
        return 0
    log = log.copy()
    log["season"] = pd.to_numeric(log["season"], errors="coerce")
    log["week"] = pd.to_numeric(log.get("week"), errors="coerce")
    d2w = _date_to_week()

    # index player-week rows by (key, season, week) -> the row's values
    idx = {}
    for row in log.to_dict("records"):
        k = (str(row.get("_key", "")), row.get("season"), row.get("week"))
        idx[k] = row

    graded = []
    for r in arc.to_dict("records"):
        stat_key = _NFL_PROP_STAT_MAP.get(str(r.get("Stat")))
        meta = _NFL_FLOOR_STATS.get(stat_key) if stat_key else None
        line = pd.to_numeric(r.get("Line"), errors="coerce")
        season = pd.to_numeric(r.get("Season"), errors="coerce")
        gdate = str(r.get("GameDate") or "")[:10]
        week = d2w.get((int(season), gdate)) if pd.notna(season) and gdate else None
        actual, result = None, "PENDING"
        if meta and pd.notna(line) and week is not None and pd.notna(season):
            key = (_nfl_name_key(r.get("Player")), float(season), float(week))
            hit_row = idx.get(key)
            if hit_row is not None:
                val = 0.0
                for c in meta["cols"]:
                    v = pd.to_numeric(hit_row.get(c), errors="coerce")
                    val += float(v) if pd.notna(v) else 0.0
                actual = round(val, 1)
                result = "OVER" if val > line else ("UNDER" if val < line else "PUSH")
        gr = dict(r)
        gr["Week"] = week if week is not None else ""
        gr["Actual"] = actual if actual is not None else ""
        gr["Result"] = result
        graded.append(gr)

    out = pd.DataFrame(graded)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)
    res = out["Result"].value_counts().to_dict()
    print(f"[grade_nfl_prop_lines] graded {len(out)} archived lines -> {OUT.name} | {res}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
