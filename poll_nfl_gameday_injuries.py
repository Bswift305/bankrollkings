"""
Bankroll Kings - NFL game-day injury poll (self-gating)
=======================================================

Refreshes the NFL injury feed and re-diffs status changes FREQUENTLY on NFL game
days, so the tracker catches the ~90-minute-pre-kickoff inactive list (a move to
"Out") while there is still a window before the market fully adjusts. The regular
bk-injuries timer runs ~every 6h, which misses early-kickoff inactives.

Self-gating so it is safe to run every 20 min year-round: it no-ops unless (a) an
NFL game is scheduled TODAY (Eastern, from the schedule files) and (b) the current
Eastern hour is inside the game-day window (10:00-23:59 ET, which spans from before
the ~11:30am inactive drop for 1pm kicks through night games). Off-season and
non-game-days it exits in well under a second having done nothing.

Injuries come from a free ESPN scrape (fetch_sport_injuries), so frequent polling
costs no API quota. Lightweight -- no `app` import.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
SCHEDULE_PATHS = [
    BASE_DIR / "data" / "schedules" / "NFL_Schedule.csv",
    BASE_DIR / "data" / "schedules" / "NFL_Preseason_Schedule.csv",
]
EASTERN = ZoneInfo("America/New_York")
WINDOW_START_HOUR = 10  # inactives for 1pm ET kicks post ~11:30am ET
WINDOW_END_HOUR = 23


def _has_game_today(today_str: str) -> bool:
    for path in SCHEDULE_PATHS:
        if not path.exists():
            continue
        try:
            df = pd.read_csv(path)
        except Exception:
            continue
        if "Date" not in df.columns:
            continue
        dates = pd.to_datetime(df["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
        if (dates == today_str).any():
            return True
    return False


def main() -> int:
    now = datetime.now(EASTERN)
    today = now.strftime("%Y-%m-%d")

    if not _has_game_today(today):
        print(f"[skip] no NFL game today ({today}).")
        return 0
    if not (WINDOW_START_HOUR <= now.hour <= WINDOW_END_HOUR):
        print(f"[skip] NFL game day but outside window (ET hour {now.hour}).")
        return 0

    print(f"[run] NFL game day {today} {now.hour:02d}:{now.minute:02d} ET -- polling injuries + status changes.")
    for script in ("fetch_nfl_injuries.py", "track_nfl_injury_changes.py"):
        result = subprocess.run([sys.executable, str(BASE_DIR / script)], cwd=str(BASE_DIR))
        if result.returncode != 0:
            print(f"  {script} exited {result.returncode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
