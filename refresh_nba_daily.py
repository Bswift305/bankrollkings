from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

from services.run_outcomes import props_step_outcome, record_child_outcomes

BASE_DIR = Path(__file__).resolve().parent
NON_BLOCKING_STEPS = {"runtime_snapshots"}
# The player-props fetch must NEVER abort the rest of the NBA chain (injuries, officiating, calibration,
# board QC) just because props are legitimately unavailable early in the season (directive #3). Its
# true outcome is derived from the response-shape receipt; a benign NO_MARKETS_POSTED / NO_ACTIVE_EVENTS
# lets the chain finish cleanly, while a VALIDATION_FAILED / PROVIDER_ERROR leaves the run DEGRADED
# (non-zero exit) WITHOUT skipping the safe downstream work.
PROPS_STEP = "player_props"
PROPS_SPORT_SLUG = "basketball_nba"
PROPS_ARTIFACT = BASE_DIR / "data" / "props" / "NBA_Props.csv"


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


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

    degraded = False
    for label, command, timeout in STEPS:
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
            # Classify from the response-shape receipt (directive #2/#3). Benign -> continue cleanly;
            # alerting -> degrade the run but DO NOT abort the safe downstream steps.
            exit_code = result.returncode if not timed_out else 1
            outcome, detail, alerting = props_step_outcome(BASE_DIR, PROPS_SPORT_SLUG, PROPS_ARTIFACT,
                                                           props_mtime_before, exit_code, timed_out)
            record_child_outcomes(BASE_DIR, "nba_daily", {"player_props": outcome})
            print(f"[{outcome}] {label} seconds={elapsed:.1f} "
                  f"({'ALERT' if alerting else 'ok'}): {detail}", flush=True)
            if alerting:
                degraded = True
                print(f"[WARN] NBA props are {outcome}; continuing the rest of the NBA chain "
                      "(injuries/officiating/calibration/QC) and leaving the run DEGRADED.", flush=True)
            print()
            continue

        if timed_out:
            print()
            print(f"[FAIL] {label} timed out after {elapsed:.1f}s", flush=True)
            if label in NON_BLOCKING_STEPS:
                print(f"[WARN] Continuing because {label} is non-blocking for live NBA refresh.", flush=True)
                print()
                continue
            return 124
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

    if degraded:
        print("NBA daily refresh completed the safe work but is DEGRADED (player props validation failed "
              "or unavailable for a non-benign reason).")
        return 1
    print("NBA daily refresh completed cleanly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
