from __future__ import annotations

import subprocess
import sys
from datetime import datetime


STEPS = [
    ("playoff_results", [sys.executable, "-X", "utf8", "refresh_playoff_results.py"]),
    ("playoff_player_logs", [sys.executable, "-X", "utf8", "refresh_playoff_player_logs.py"]),
    ("game_lines", [sys.executable, "fetch_game_lines.py", "--bookmakers", "draftkings,caesars,fanduel,betmgm", "--days", "5", "--api-key", "51234f049c2e262e299d9a78d1c0a829"]),
    ("player_props", [sys.executable, "fetch_player_props.py", "--bookmakers", "draftkings,caesars,fanduel,betmgm", "--days", "5", "--api-key", "51234f049c2e262e299d9a78d1c0a829"]),
    ("injuries", [sys.executable, "-X", "utf8", "fetch_injuries.py"]),
    ("candidate_archive", [sys.executable, "archive_daily_candidates.py"]),
    ("featured_results", [sys.executable, "refresh_featured_results.py"]),
    ("all_prop_results", [sys.executable, "refresh_all_prop_results.py"]),
    ("floor_play_index", [sys.executable, "build_floor_play_index.py"]),
    ("model_calibration", [sys.executable, "calibrate_nba_model.py"]),
    ("runtime_snapshots", [sys.executable, "refresh_runtime_snapshots.py"]),
    ("series_mappings_qc", [sys.executable, "qc_nba_series_mappings.py"]),
    ("sources_qc", [sys.executable, "qc_nba_sources.py"]),
    ("contradictions_qc", [sys.executable, "qc_nba_contradictions.py", "--report-only"]),
    ("board_qc", [sys.executable, "qc_nba_board.py"]),
]


def main() -> int:
    print("=" * 60)
    print("BANKROLL KINGS - NBA DAILY REFRESH")
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

    print("NBA daily refresh completed cleanly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
