from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from services.run_outcomes import props_step_outcome, record_child_outcomes

BASE_DIR = Path(__file__).resolve().parent
NON_BLOCKING_STEPS = {"runtime_snapshots"}
# Player props must NEVER abort the rest of the MLB chain (umpires/context/calibration/QC) just because
# props are legitimately unavailable (directive #3) -- mirrors NBA. Its true outcome comes from the
# response-shape receipt; benign finishes the chain, non-benign leaves the run DEGRADED.
PROPS_STEP = "player_props"
PROPS_SPORT_SLUG = "baseball_mlb"
PROPS_ARTIFACT = BASE_DIR / "data" / "props" / "MLB_Props.csv"


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


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

    degraded = False
    for label, command, timeout in _build_steps():
        started = datetime.now()
        print(f"[STEP] {label} timeout={timeout}s", flush=True)
        props_mtime_before = _mtime(PROPS_ARTIFACT) if label == PROPS_STEP else 0.0
        try:
            result = subprocess.run(command, timeout=timeout)
            timed_out = False
        except subprocess.TimeoutExpired:
            result = None
            timed_out = True
        elapsed = (datetime.now() - started).total_seconds()

        if label == PROPS_STEP:
            exit_code = result.returncode if not timed_out else 1
            outcome, detail, alerting = props_step_outcome(BASE_DIR, PROPS_SPORT_SLUG, PROPS_ARTIFACT,
                                                           props_mtime_before, exit_code, timed_out)
            record_child_outcomes(BASE_DIR, "mlb_daily", {"player_props": outcome})
            print(f"[{outcome}] {label} seconds={elapsed:.1f} "
                  f"({'ALERT' if alerting else 'ok'}): {detail}", flush=True)
            if alerting:
                degraded = True
                print(f"[WARN] MLB props are {outcome}; continuing the rest of the MLB chain "
                      "(umpires/context/calibration/QC) and leaving the run DEGRADED.", flush=True)
            print()
            continue

        if timed_out:
            print()
            print(f"[FAIL] {label} timed out after {elapsed:.1f}s", flush=True)
            if label in NON_BLOCKING_STEPS:
                print(f"[WARN] Continuing because {label} is non-blocking for live MLB refresh.", flush=True)
                print()
                continue
            return 124
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

    if degraded:
        print("MLB daily refresh completed the safe work but is DEGRADED (player props validation failed "
              "or unavailable for a non-benign reason).")
        return 1
    print("MLB daily refresh completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
