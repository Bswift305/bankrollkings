from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime


NON_BLOCKING_STEPS = {"runtime_snapshots"}


def _build_steps() -> list[tuple[str, list[str], int]]:
    steps: list[tuple[str, list[str], int]] = [
        ("schedule", [sys.executable, "-X", "utf8", "fetch_mlb_schedule.py", "--days", "14"], 120),
        ("gamelogs", [sys.executable, "-X", "utf8", "fetch_mlb_gamelogs.py", "--initial-days", "10"], 240),
    ]
    api_key = os.getenv("ODDS_API_KEY") or os.getenv("THE_ODDS_API_KEY")
    if api_key:
        steps.extend([
            ("game_lines", [sys.executable, "fetch_mlb_game_lines.py", "--bookmakers", "draftkings,williamhill_us,fanduel,betmgm,betrivers,fanatics", "--days", "5", "--api-key", api_key], 180),
            ("player_props", [sys.executable, "fetch_mlb_player_props.py", "--bookmakers", "draftkings,williamhill_us,fanduel,betmgm,betrivers,fanatics", "--days", "5", "--api-key", api_key], 240),
            ("market_key_audit", [sys.executable, "audit_mlb_market_keys.py"], 90),
        ])
    steps.append(("umpire_assignments", [sys.executable, "fetch_mlb_umpire_assignments.py"], 120))
    steps.append(("umpire_context", [sys.executable, "build_mlb_umpire_context.py"], 90))
    steps.append(("officiating_context", [sys.executable, "build_officiating_context.py"], 90))
    steps.append(("game_context", [sys.executable, "build_mlb_game_context.py"], 120))
    steps.append(("statcast_context", [sys.executable, "refresh_mlb_statcast.py"], 360))
    steps.append(("combined_prop_coverage", [sys.executable, "audit_combined_prop_coverage.py"], 90))
    steps.append(("readiness_qc", [sys.executable, "qc_mlb_readiness.py", "--skip-routes"], 90))
    steps.append(("contradictions_qc", [sys.executable, "qc_mlb_contradictions.py", "--fast", "--report-only"], 240))
    steps.append(("refresh_manifest_live", [sys.executable, "write_mlb_refresh_manifest.py"], 90))
    # Candidate archiving is a review-center/governance job. Keep the daily
    # MLB refresh focused on live data freshness so one heavy archive pass
    # cannot block updated boards.
    # Result grading reads the full candidate archive and belongs in the
    # review/governance lane, not the live MLB data refresh.
    steps.append(("model_calibration", [sys.executable, "calibrate_mlb_model.py"], 90))
    steps.append(("runtime_snapshots", [sys.executable, "refresh_mlb_runtime_snapshots.py"], 180))
    steps.append(("refresh_manifest_final", [sys.executable, "write_mlb_refresh_manifest.py"], 90))
    return steps


def main() -> int:
    print("=" * 60)
    print("BANKROLL KINGS - MLB DAILY REFRESH")
    print("=" * 60)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    for label, command, timeout in _build_steps():
        started = datetime.now()
        print(f"[STEP] {label} timeout={timeout}s", flush=True)
        try:
            result = subprocess.run(command, timeout=timeout)
        except subprocess.TimeoutExpired:
            elapsed = (datetime.now() - started).total_seconds()
            print()
            print(f"[FAIL] {label} timed out after {elapsed:.1f}s", flush=True)
            if label in NON_BLOCKING_STEPS:
                print(f"[WARN] Continuing because {label} is non-blocking for live MLB refresh.", flush=True)
                print()
                continue
            return 124
        elapsed = (datetime.now() - started).total_seconds()
        if result.returncode != 0:
            print()
            print(f"[FAIL] {label} exited with code {result.returncode} after {elapsed:.1f}s", flush=True)
            if label in NON_BLOCKING_STEPS:
                print(f"[WARN] Continuing because {label} is non-blocking for live MLB refresh.", flush=True)
                print()
                continue
            return result.returncode
        print(f"[PASS] {label} seconds={elapsed:.1f}", flush=True)
        print()

    print("MLB daily refresh completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
