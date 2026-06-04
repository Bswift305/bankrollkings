from __future__ import annotations

import subprocess
import sys
from datetime import datetime


STEPS = [
    ("player_logs", [sys.executable, "-X", "utf8", "refresh_wnba_player_logs.py"]),
    ("game_lines", [sys.executable, "fetch_wnba_game_lines.py", "--days", "5"]),
    ("player_props", [sys.executable, "fetch_wnba_player_props.py", "--days", "5"]),
    ("injuries", [sys.executable, "-X", "utf8", "fetch_wnba_injuries.py"]),
    ("basketball_officiating", [sys.executable, "fetch_basketball_officiating_assignments.py"]),
    ("officiating_context", [sys.executable, "build_officiating_context.py"]),
    ("candidate_archive", [sys.executable, "archive_daily_candidates.py"]),
    ("featured_results", [sys.executable, "refresh_wnba_featured_results.py"]),
    ("all_prop_results", [sys.executable, "refresh_all_prop_results.py"]),
    ("floor_play_index", [sys.executable, "build_floor_play_index.py"]),
    ("combined_prop_coverage", [sys.executable, "audit_combined_prop_coverage.py"]),
    ("model_calibration", [sys.executable, "calibrate_wnba_model.py"]),
    ("runtime_snapshots", [sys.executable, "refresh_runtime_snapshots.py"]),
]


def main() -> int:
    print("=" * 60)
    print("BANKROLL KINGS - WNBA DAILY REFRESH")
    print("=" * 60)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    for label, command in STEPS:
        print(f"[STEP] {label}")
        result = subprocess.run(command)
        if result.returncode != 0:
            print()
            print(f"[FAIL] {label} exited with code {result.returncode}")
            return result.returncode
        print(f"[PASS] {label}")
        print()

    print("WNBA daily refresh completed cleanly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
