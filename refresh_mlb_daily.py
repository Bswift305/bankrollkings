from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime


def _build_steps() -> list[tuple[str, list[str]]]:
    steps: list[tuple[str, list[str]]] = [
        ("schedule", [sys.executable, "-X", "utf8", "fetch_mlb_schedule.py", "--days", "14"]),
        ("gamelogs", [sys.executable, "-X", "utf8", "fetch_mlb_gamelogs.py", "--initial-days", "10"]),
    ]
    api_key = os.getenv("ODDS_API_KEY") or os.getenv("THE_ODDS_API_KEY")
    if api_key:
        steps.extend([
            ("game_lines", [sys.executable, "fetch_mlb_game_lines.py", "--bookmakers", "draftkings,williamhill_us,fanduel,betmgm,betrivers,fanatics", "--days", "5", "--api-key", api_key]),
            ("player_props", [sys.executable, "fetch_mlb_player_props.py", "--bookmakers", "draftkings,williamhill_us,fanduel,betmgm,betrivers,fanatics", "--days", "5", "--api-key", api_key]),
            ("market_key_audit", [sys.executable, "audit_mlb_market_keys.py"]),
        ])
    steps.append(("game_context", [sys.executable, "build_mlb_game_context.py"]))
    steps.append(("readiness_qc", [sys.executable, "qc_mlb_readiness.py"]))
    steps.append(("contradictions_qc", [sys.executable, "qc_mlb_contradictions.py", "--report-only"]))
    steps.append(("candidate_archive", [sys.executable, "archive_daily_candidates.py"]))
    steps.append(("featured_results", [sys.executable, "refresh_mlb_featured_results.py"]))
    steps.append(("all_prop_results", [sys.executable, "refresh_all_prop_results.py"]))
    steps.append(("model_calibration", [sys.executable, "calibrate_mlb_model.py"]))
    steps.append(("runtime_snapshots", [sys.executable, "refresh_runtime_snapshots.py"]))
    steps.append(("refresh_manifest", [sys.executable, "write_mlb_refresh_manifest.py"]))
    return steps


def main() -> int:
    print("=" * 60)
    print("BANKROLL KINGS - MLB DAILY REFRESH")
    print("=" * 60)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    for label, command in _build_steps():
        print(f"[STEP] {label}")
        result = subprocess.run(command)
        if result.returncode != 0:
            print()
            print(f"[FAIL] {label} exited with code {result.returncode}")
            return result.returncode
        print(f"[PASS] {label}")
        print()

    print("MLB daily refresh completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
