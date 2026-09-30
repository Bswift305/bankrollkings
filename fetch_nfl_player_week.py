#!/usr/bin/env python3
"""Fetch the CURRENT-season nflverse weekly player stats and persist them, so the prop
engines (Prop Floor / Featured Players usage / Hot Hand) AND the prop-line grader always
read FRESH in-season data.

`_nfl_player_week_data()` in app.py builds its player-week log from the static historical
CSVs (prior seasons) plus the current season's nflverse weekly parquet. nflverse only ever
publishes the single season file (it rewrites it as each week finalizes) -- and nothing on
prod was refreshing our copy. The in-season base was a one-time local build (jw26.parquet)
stuck at weeks 1-2, so on the server the floor/usage/hot-hand reads and the grader silently
ran on stale data (locally it left every recent prop PENDING because the resolved week
wasn't there). This closes that hole.

Writes data/tracking/_nflverse_stats_<season>.parquet -- exactly the path
`_nfl_player_week_data()` reads for the current season. data/tracking is gitignored, so
PROD accumulates its own fresh copy (like the other tracking ledgers). Idempotent:
overwrites the season file each run via an atomic replace. Wire into run_daily.py BEFORE
grade_nfl_prop_lines.py.
"""
from __future__ import annotations

import argparse
import os
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "data" / "tracking"
STATS_URL = ("https://github.com/nflverse/nflverse-data/releases/download/"
             "stats_player/stats_player_week_{season}.parquet")


def current_nfl_season() -> int:
    """NFL season N spans Sep N -> Feb N+1, so Jan/Feb still belongs to the prior year."""
    try:
        from services.timeutils import to_eastern_date_str  # noqa
        s = to_eastern_date_str(datetime.utcnow().isoformat() + "Z")
        y, m = int(s[:4]), int(s[5:7])
    except Exception:
        n = datetime.now()
        y, m = n.year, n.month
    return y if m >= 3 else y - 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch current-season nflverse weekly player stats.")
    ap.add_argument("--season", type=int, default=None, help="Override the season (default: current).")
    ap.add_argument("--source", default=None, help="Use a local parquet instead of downloading.")
    args = ap.parse_args()
    season = args.season or current_nfl_season()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"_nflverse_stats_{season}.parquet"

    tmp = None
    try:
        if args.source:
            df = pd.read_parquet(args.source)
        else:
            fd, tmp = tempfile.mkstemp(prefix=f"nflwk_{season}_", suffix=".parquet")
            os.close(fd)
            urllib.request.urlretrieve(STATS_URL.format(season=season), tmp)
            df = pd.read_parquet(tmp)
    except Exception as exc:
        # Off-season / not-yet-published seasons 404 -- leave any existing file untouched.
        print(f"[fetch_nfl_player_week] could not fetch season {season}: {exc}")
        return 0 if out.exists() else 1
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass

    if df is None or df.empty:
        print(f"[fetch_nfl_player_week] season {season}: empty feed; left existing file untouched")
        return 0
    weeks = sorted(int(w) for w in pd.to_numeric(df.get("week"), errors="coerce").dropna().unique())
    # atomic write so a concurrent web read never sees a half-written parquet
    fd, tmp2 = tempfile.mkstemp(prefix=f"nflwk_out_{season}_", suffix=".parquet", dir=str(OUT_DIR))
    os.close(fd)
    try:
        df.to_parquet(tmp2, index=False)
        os.replace(tmp2, out)
    finally:
        if os.path.exists(tmp2):
            try:
                os.remove(tmp2)
            except OSError:
                pass
    print(f"[fetch_nfl_player_week] season {season}: {len(df):,} rows, weeks {weeks} -> {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
