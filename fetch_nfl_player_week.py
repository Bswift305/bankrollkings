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
import time
import urllib.request
from datetime import date, datetime
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


# Week-1 Thursday (ET) per season. Keep in sync with NFL_SEASON_WEEK1_THURSDAY in app.py:
# both the heat-map freshness gate and this fetcher's retry decide "which week should be
# final by now" from the same anchor. Add each new season's opener here.
NFL_SEASON_WEEK1 = {
    2025: date(2025, 9, 4),
    2026: date(2026, 9, 10),
}


def expected_completed_week(season: int, today: date | None = None):
    """How many weeks of `season` SHOULD be final as of `today` (ET date). A week runs
    Thu->Mon and is only complete after its Tuesday, so the boundary falls on Tuesday.
    Returns None when we have no Week-1 anchor for the season (make no staleness claim)."""
    today = today or _today_et()
    wk1 = NFL_SEASON_WEEK1.get(season)
    if wk1 is None or today < wk1:
        return 0 if (wk1 is not None and today < wk1) else None
    days = (today - wk1).days
    cur_week = days // 7 + 1
    completed = cur_week if (days % 7) >= 5 else cur_week - 1
    return max(0, min(completed, 18))


def _today_et() -> date:
    try:
        from services.timeutils import to_eastern_date_str
        s = to_eastern_date_str(datetime.utcnow().isoformat() + "Z")
        return date(int(s[:4]), int(s[5:7]), int(s[8:10]))
    except Exception:
        return datetime.now().date()


def _fetch_frame(season: int, source: str | None):
    """Download (or read --source) the season parquet. Returns a DataFrame or None on failure.
    Raises nothing -- a 404/offline season is a None return, not a crash."""
    tmp = None
    try:
        if source:
            return pd.read_parquet(source)
        fd, tmp = tempfile.mkstemp(prefix=f"nflwk_{season}_", suffix=".parquet")
        os.close(fd)
        urllib.request.urlretrieve(STATS_URL.format(season=season), tmp)
        return pd.read_parquet(tmp)
    except Exception as exc:
        print(f"[fetch_nfl_player_week] could not fetch season {season}: {exc}")
        return None
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass


def _max_week(df) -> int:
    if df is None or df.empty:
        return 0
    wk = pd.to_numeric(df.get("week"), errors="coerce").dropna()
    return int(wk.max()) if not wk.empty else 0


def _on_disk_week(season: int):
    """Inspect the on-disk parquet for `season` WITHOUT distinguishing-error-into-data. Returns
    (status, info):
      'missing'    -> the file is absent; info = 0 (legitimately no data yet).
      'ok'         -> readable; info = highest week present (0 if the file has no week rows).
      'unreadable' -> the file EXISTS but could not be read (a permission or corruption error);
                      info = the exception. This must NOT be reported as 'week 0' -- a healthy
                      parquet an operator simply lacks permission to read (e.g. run as ssm-user
                      instead of ubuntu) would otherwise look like missing data.
    No network -- used by --check-only to decide whether a post-week retry is still needed."""
    out = OUT_DIR / f"_nflverse_stats_{season}.parquet"
    if not out.exists():
        return "missing", 0
    try:
        return "ok", _max_week(pd.read_parquet(out))
    except Exception as exc:
        return "unreadable", exc


def _check_only_result(season: int, want_week):
    """Decide the --check-only (exit_code, message). Separated from main() so it is unit-testable.
    Exit 0 = up to date (or no calendar anchor); 2 = behind the completed week; 3 = the on-disk
    file could not be read (permission/corruption) -- a DISTINCT failure, never a false 'week 0'."""
    status, info = _on_disk_week(season)
    if status == "unreadable":
        return 3, (f"season {season}: cannot read the on-disk parquet ({type(info).__name__}: {info}). "
                   f"The file exists but is not readable -- run as the owner (e.g. "
                   f"`sudo -u ubuntu ...`). This is NOT missing data.")
    have = info
    if want_week is None:
        return 0, f"season {season} has week {have}; no calendar anchor"
    if have >= want_week:
        return 0, f"season {season} week {have} >= completed week {want_week}"
    where = "no on-disk parquet (week 0)" if status == "missing" else f"week {have}"
    return 2, f"season {season} {where} < completed week {want_week}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch current-season nflverse weekly player stats.")
    ap.add_argument("--season", type=int, default=None, help="Override the season (default: current).")
    ap.add_argument("--source", default=None, help="Use a local parquet instead of downloading.")
    ap.add_argument("--retries", type=int, default=0,
                    help="If the feed is behind the completed week, re-download up to N times "
                         "(use on a post-game Mon/Tue cadence; default 0 for the daily run).")
    ap.add_argument("--retry-wait", type=int, default=300,
                    help="Seconds to wait between retries (default 300).")
    ap.add_argument("--require-week", type=int, default=None,
                    help="The completed week the feed MUST contain. Default: computed from the "
                         "calendar. Exit 2 if still missing after retries (so an ops wrapper can "
                         "keep retrying); the plain daily run leaves this unset and never exit-2s.")
    ap.add_argument("--gate", action="store_true",
                    help="Gate on the calendar's completed week (like --require-week <computed>): "
                         "exit 2 if the feed is still behind it. For the post-week retry timer.")
    ap.add_argument("--check-only", action="store_true",
                    help="No download: report whether the on-disk parquet already holds the "
                         "calendar's completed week. Exit 0 if present (or no anchor), 2 if behind, "
                         "3 if the file exists but cannot be read (permission/corruption).")
    args = ap.parse_args()
    season = args.season or current_nfl_season()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"_nflverse_stats_{season}.parquet"

    # The week that SHOULD be final by now. --require-week forces it; --gate uses the calendar;
    # otherwise the calendar decides for reporting only. None = no anchor -> no freshness claim.
    if args.require_week is not None:
        want_week = args.require_week
    else:
        want_week = expected_completed_week(season)
    gating = (args.require_week is not None) or args.gate

    if args.check_only:
        code, msg = _check_only_result(season, want_week)
        print(f"[fetch_nfl_player_week] check: {msg}")
        return code

    df = None
    attempts = max(0, args.retries) + 1
    for i in range(attempts):
        df = _fetch_frame(season, args.source)
        have = _max_week(df)
        if want_week is None or have >= want_week or args.source:
            break
        if i < attempts - 1:
            print(f"[fetch_nfl_player_week] season {season}: feed has week {have}, "
                  f"completed week {want_week} not published yet -- retry {i + 1}/{attempts - 1} "
                  f"in {args.retry_wait}s")
            time.sleep(max(0, args.retry_wait))

    if df is None:
        # Off-season / not-yet-published season, or a transient network failure. Leave any
        # existing file untouched so stale-but-real data is never replaced with nothing.
        return 0 if out.exists() else 1
    if df.empty:
        print(f"[fetch_nfl_player_week] season {season}: empty feed; left existing file untouched")
        return 0

    weeks = sorted(int(w) for w in pd.to_numeric(df.get("week"), errors="coerce").dropna().unique())
    have = _max_week(df)
    # atomic write so a concurrent web read never sees a half-written parquet. Always write the
    # freshest data we obtained, even if still a week behind -- more weeks is never worse.
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

    if want_week is not None and have < want_week:
        # The heat map / grader will treat this as 'pending latest results' and not present last
        # week's streaks as current. Signal the shortfall so a retry wrapper knows to come back.
        msg = (f"[fetch_nfl_player_week] FRESHNESS: season {season} completed week {want_week} "
               f"not yet in the feed (have week {have}).")
        if gating:
            print(msg + " exit 2 -> retry later.")
            return 2
        print(msg + " Will pick it up on the next run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
