from __future__ import annotations

import subprocess
import sys
from datetime import datetime


NON_BLOCKING_STEPS = {"runtime_snapshots"}


STEPS = [
    ("playoff_results", [sys.executable, "-X", "utf8", "refresh_playoff_results.py"], 240),
    ("playoff_player_logs", [sys.executable, "-X", "utf8", "refresh_playoff_player_logs.py"], 480),
    ("game_lines", [sys.executable, "fetch_game_lines.py", "--bookmakers", "draftkings,caesars,fanduel,betmgm", "--days", "5"], 180),
    ("player_props", [sys.executable, "fetch_player_props.py", "--bookmakers", "draftkings,caesars,fanduel,betmgm", "--days", "5"], 240),
    ("injuries", [sys.executable, "-X", "utf8", "fetch_injuries.py"], 180),
    ("basketball_officiating", [sys.executable, "fetch_basketball_officiating_assignments.py"], 120),
    ("officiating_context", [sys.executable, "build_officiating_context.py"], 90),
    ("combined_prop_coverage", [sys.executable, "audit_combined_prop_coverage.py"], 90),
    # Review/archive work is intentionally outside the live NBA refresh lane.
    # Run `refresh_all_prop_results.py --sport nba` separately after live data
    # is current so historical grading cannot block updated boards.
    ("model_calibration", [sys.executable, "calibrate_nba_model.py"], 120),
    ("runtime_snapshots", [sys.executable, "refresh_runtime_snapshots.py", "--sports", "nba", "--skip-prewarm"], 300),
    ("series_mappings_qc", [sys.executable, "qc_nba_series_mappings.py"], 90),
    ("sources_qc", [sys.executable, "qc_nba_sources.py"], 90),
    ("contradictions_qc", [sys.executable, "qc_nba_contradictions.py", "--report-only"], 240),
    ("board_qc", [sys.executable, "qc_nba_board.py"], 120),
]


def main() -> int:
    print("=" * 60)
    print("BANKROLL KINGS - NBA DAILY REFRESH")
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
                print(f"[WARN] Continuing because {label} is non-blocking for live NBA refresh.", flush=True)
                print()
                continue
            return 124
        elapsed = (datetime.now() - started).total_seconds()
        if result.returncode != 0:
            print()
            print(f"[FAIL] {label} exited with code {result.returncode} after {elapsed:.1f}s", flush=True)
            if label in NON_BLOCKING_STEPS:
                print(f"[WARN] Continuing because {label} is non-blocking for live NBA refresh.", flush=True)
                print()
                continue
            return result.returncode
        print(f"[PASS] {label} seconds={elapsed:.1f}", flush=True)
        print()

    print("NBA daily refresh completed cleanly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
