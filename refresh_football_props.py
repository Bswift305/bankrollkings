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
from pathlib import Path

from services.run_outcomes import (
    aggregate_parent,
    classify_props_child,
    is_alerting,
    load_shape_receipt,
)

BASE_DIR = Path(__file__).resolve().parent

# (label, command, timeout, sport_slug, artifact) -- sport_slug keys the response-shape receipt and
# artifact is the file whose mtime advance proves a publish. The parent derives its result from these
# children's OUTCOMES (directive #3): it never reports a bare PASS when an artifact did not advance
# without a PROVEN benign outcome (NO_ACTIVE_EVENTS / NO_MARKETS_POSTED).
STEPS = [
    ("nfl_player_props", [sys.executable, "fetch_nfl_player_props.py", "--days", "7"], 300,
     "americanfootball_nfl", BASE_DIR / "data" / "props" / "NFL_Props.csv"),
    ("ncaaf_player_props", [sys.executable, "fetch_ncaaf_player_props.py", "--days", "7"], 300,
     "americanfootball_ncaaf", BASE_DIR / "data" / "props" / "NCAAF_Props.csv"),
]


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def main() -> int:
    print("=" * 60)
    print("BANKROLL KINGS - FOOTBALL PLAYER PROPS REFRESH")
    print("=" * 60)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if not (os.getenv("ODDS_API_KEY") or "").strip():
        print("refresh_football_props: ODDS_API_KEY not set - skipping football props refresh.")
        return 0

    print()
    outcomes: dict[str, str] = {}
    for label, command, timeout, sport_slug, artifact in STEPS:
        started = datetime.now()
        print(f"[STEP] {label} timeout={timeout}s", flush=True)
        mtime_before = _mtime(artifact)
        try:
            result = subprocess.run(command, timeout=timeout)
            exit_code = result.returncode
        except subprocess.TimeoutExpired:
            elapsed = (datetime.now() - started).total_seconds()
            print(f"[PROVIDER_ERROR] {label} timed out after {elapsed:.1f}s", flush=True)
            outcomes[label] = "PROVIDER_ERROR"
            continue
        elapsed = (datetime.now() - started).total_seconds()
        # Derive the TRUE outcome from the response-shape receipt + whether the artifact advanced -- NOT
        # from the child exit code alone. fetch_player_props returns 1 whenever it preserves last-known-
        # good, which happens for a LEGITIMATE NO_MARKETS_POSTED as well as a real failure; only the
        # receipt separates them (directive #2).
        advanced = _mtime(artifact) > mtime_before
        receipt = load_shape_receipt(BASE_DIR, sport_slug)
        outcome, detail = classify_props_child(exit_code, advanced, receipt)
        outcomes[label] = outcome
        tag = "ALERT" if is_alerting(outcome) else "ok"
        print(f"[{outcome}] {label} seconds={elapsed:.1f} exit={exit_code} ({tag}): {detail}", flush=True)
        print()

    summary, degraded = aggregate_parent(outcomes)
    print(f"OUTCOME football_player_props: {summary}")
    if degraded:
        # At least one child is alerting (VALIDATION_FAILED / PROVIDER_ERROR / STALE). The parent must
        # NOT report a clean PASS -- exit non-zero so the operator records it and Run Status degrades.
        print("Football player props refresh is DEGRADED (an artifact did not advance for a non-benign reason).")
        return 1
    print("Football player props refresh completed (all children benign).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
