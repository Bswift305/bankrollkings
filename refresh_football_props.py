"""Fetch NFL + NCAAF player props into data/props/{NFL,NCAAF}_Props.csv.

Companion to refresh_football_line_movement.py (which fetches game lines). That
one runs on prod; this one did NOT -- the player-props fetch lived only in the
Windows batch REFRESH_FOOTBALL_DATA.bat, so prod fetched football GAME LINES
every day but never player PROPS. The board, archiving and grading are all ready
for football (stat map fixed, dry-run archives 24/24, grading 15/15), but with no
props feed there is nothing for them to act on -- the same silent gap that left
college football with no data until it was wired in explicitly.

Cost profile is self-gating. The shared fetcher lists events in the --days
window first, then pulls props per event only for games inside it. In the
offseason no games fall within 7 days, so this is one cheap events call that
returns nothing; it starts pulling real props automatically once games come
within a week (NFL preseason ~early Aug, Week 1 ~early Sep). --days 7 matches the
batch file and the window in which books actually post player props.

Skips gracefully (exit 0) when ODDS_API_KEY is absent, mirroring the batch guard
and build_nfl_gamelogs.py, so the daily chain never fails on an environment
without the key.

Run: python refresh_football_props.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime

STEPS = [
    ("nfl_player_props", [sys.executable, "fetch_nfl_player_props.py", "--days", "7"], 300),
    ("ncaaf_player_props", [sys.executable, "fetch_ncaaf_player_props.py", "--days", "7"], 300),
]


def main() -> int:
    print("=" * 60)
    print("BANKROLL KINGS - FOOTBALL PLAYER PROPS REFRESH")
    print("=" * 60)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if not (os.getenv("ODDS_API_KEY") or "").strip():
        print("refresh_football_props: ODDS_API_KEY not set - skipping football props refresh.")
        return 0

    print()
    failures = 0
    for label, command, timeout in STEPS:
        started = datetime.now()
        print(f"[STEP] {label} timeout={timeout}s", flush=True)
        try:
            result = subprocess.run(command, timeout=timeout)
        except subprocess.TimeoutExpired:
            elapsed = (datetime.now() - started).total_seconds()
            print(f"[FAIL] {label} timed out after {elapsed:.1f}s", flush=True)
            failures += 1
            continue
        elapsed = (datetime.now() - started).total_seconds()
        if result.returncode != 0:
            # One sport failing (e.g. NCAAF feed hiccup) must not sink the other.
            print(f"[FAIL] {label} exited with code {result.returncode} after {elapsed:.1f}s", flush=True)
            failures += 1
            continue
        print(f"[PASS] {label} seconds={elapsed:.1f}", flush=True)
        print()

    if failures:
        print(f"Football player props refresh finished with {failures} failure(s).")
        return 1
    print("Football player props refresh completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
