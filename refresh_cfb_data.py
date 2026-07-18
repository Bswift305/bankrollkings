"""Refresh the college-football (CFBD) data set.

Server-side equivalent of the CFB portion of batch/REFRESH_FOOTBALL_DATA.bat.
That batch file only ever ran on the Windows dev box, so prod had a valid
CFBD_API_KEY but no refresh path at all -- every NCAAF data file was missing on
the server and the CFB product had nothing to render.

Season years are derived, not hardcoded: the season being *built toward* is the
current calendar year and the last completed season is the year before it. That
holds year-round (in Jan the prior season has just finished bowls). The fetchers
themselves take --fallback-year and label the source year in their output, so
before CFBD publishes a new season's rosters/returning-production they degrade
to last year's data honestly rather than writing empty files.

Skips gracefully (exit 0) when CFBD_API_KEY is absent, mirroring the batch
file's guard and build_nfl_gamelogs.py, so the daily chain does not fail on
environments without the key.

Run: python refresh_cfb_data.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _steps(season: int, last_season: int) -> list[tuple[str, list[str], int]]:
    """Canonical CFB refresh order (matches REFRESH_FOOTBALL_DATA.bat steps 5-8).

    The player master is built last: it joins the roster with last season's
    player stats, so both must already be on disk.
    """
    return [
        ("CFB current roster", ["fetch_cfbd_current_roster.py",
                                "--year", str(season),
                                "--fallback-year", str(last_season)], 900),
        ("CFB player stats", ["fetch_cfbd_player_stats.py",
                              "--year", str(last_season)], 900),
        ("CFB returning production", ["fetch_cfbd_returning_production.py",
                                      "--year", str(season),
                                      "--fallback-year", str(last_season)], 420),
        ("CFB transfer portal", ["fetch_cfbd_transfer_portal.py",
                                 "--year", str(season)], 420),
        ("CFB player master", ["build_ncaaf_player_master.py",
                               "--last-season", str(last_season)], 600),
    ]


def main() -> int:
    if not (os.getenv("CFBD_API_KEY") or "").strip():
        print("refresh_cfb_data: CFBD_API_KEY not set - skipping CFB refresh.")
        return 0

    season = datetime.now().year
    last_season = season - 1
    print(f"CFB refresh | season {season} | last completed {last_season}")

    failures: list[str] = []
    for label, argv, timeout in _steps(season, last_season):
        script = BASE_DIR / argv[0]
        if not script.exists():
            print(f"[SKIP] {label}: {argv[0]} not found.")
            continue
        command = [sys.executable, str(script), *argv[1:]]
        print(f"[RUN ] {label}")
        try:
            result = subprocess.run(
                command, cwd=str(BASE_DIR), timeout=timeout,
                capture_output=True, text=True,
            )
        except subprocess.TimeoutExpired:
            print(f"[FAIL] {label}: timed out after {timeout}s.")
            failures.append(label)
            continue
        tail = (result.stdout or result.stderr or "").strip().splitlines()
        if tail:
            print(f"       {tail[-1]}")
        if result.returncode != 0:
            print(f"[FAIL] {label}: exit {result.returncode}.")
            failures.append(label)

    if failures:
        print(f"CFB refresh finished with {len(failures)} failure(s): {', '.join(failures)}")
        return 1
    print("CFB refresh complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
