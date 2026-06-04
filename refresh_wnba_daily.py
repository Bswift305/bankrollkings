from __future__ import annotations

import subprocess
import sys
from datetime import datetime


NON_BLOCKING_STEPS = {"runtime_snapshots"}


STEPS = [
    ("player_logs", [sys.executable, "-X", "utf8", "refresh_wnba_player_logs.py"], 480),
    ("game_lines", [sys.executable, "fetch_wnba_game_lines.py", "--days", "5"], 300),
    ("player_props", [sys.executable, "fetch_wnba_player_props.py", "--days", "5"], 300),
    ("injuries", [sys.executable, "-X", "utf8", "fetch_wnba_injuries.py"], 180),
    ("basketball_officiating", [sys.executable, "fetch_basketball_officiating_assignments.py"], 120),
    ("officiating_context", [sys.executable, "build_officiating_context.py"], 90),
    ("candidate_archive", [sys.executable, "archive_daily_candidates.py"], 300),
    ("featured_results", [sys.executable, "refresh_wnba_featured_results.py"], 300),
    # Review/archive work is intentionally outside the live WNBA refresh lane.
    # Run `refresh_all_prop_results.py` separately after live data is current so
    # historical grading cannot block updated boards (mirrors the NBA lane).
    ("floor_play_index", [sys.executable, "build_floor_play_index.py"], 300),
    ("combined_prop_coverage", [sys.executable, "audit_combined_prop_coverage.py"], 90),
    ("model_calibration", [sys.executable, "calibrate_wnba_model.py"], 300),
    ("runtime_snapshots", [sys.executable, "refresh_runtime_snapshots.py", "--sports", "wnba", "--skip-prewarm"], 300),
]


def main() -> int:
    print("=" * 60)
    print("BANKROLL KINGS - WNBA DAILY REFRESH")
    print("=" * 60)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    for label, command, timeout in STEPS:
        started = datetime.now()
        print(f"[STEP] {label} timeout={timeout}s", flush=True)
        try:
            result = subprocess.run(command, timeout=timeout)
        except subprocess.TimeoutExpired:
            elapsed = (datetime.now() - started).total_seconds()
            print()
            print(f"[FAIL] {label} timed out after {elapsed:.1f}s", flush=True)
            if label in NON_BLOCKING_STEPS:
                print(f"[WARN] Continuing because {label} is non-blocking for live WNBA refresh.", flush=True)
                print()
                continue
            return 124
        elapsed = (datetime.now() - started).total_seconds()
        if result.returncode != 0:
            print()
            print(f"[FAIL] {label} exited with code {result.returncode} after {elapsed:.1f}s", flush=True)
            if label in NON_BLOCKING_STEPS:
                print(f"[WARN] Continuing because {label} is non-blocking for live WNBA refresh.", flush=True)
                print()
                continue
            return result.returncode
        print(f"[PASS] {label} seconds={elapsed:.1f}", flush=True)
        print()

    print("WNBA daily refresh completed cleanly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
