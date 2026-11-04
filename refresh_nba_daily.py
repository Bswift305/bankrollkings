from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from services import nba_market
from services import nba_market_budget as budget
from services.run_outcomes import (
    LINES_READY, PROVIDER_ERROR, SCHEDULE_UNAVAILABLE, SKIPPED_BLOCKED_BY_LINES, VALIDATION_FAILED,
    NO_FRESH_AFTER_LOCK, EXIT_HARD_FAILURE, record_child_outcomes, runner_exit_for_child,
)

# v5: bk-daily's NBA lines + props steps call the SHARED ensure API (services/nba_market.ensure_nba_lines /
# ensure_nba_props) -- the same canonical stage command, reuse/lock policy and timeouts as the orchestrator
# (refresh_nba_market.py). Lock wait and step timeouts come from the ONE timeout table
# (services/nba_market_budget.py); nothing here hard-codes them.
LINES_LOCK_WAIT_SECONDS = budget.LOCK_WAIT_SECONDS
PROPS_LOCK_WAIT_SECONDS = budget.LOCK_WAIT_SECONDS
NBA_DAILY_CALLER = "nba_daily"

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

# Game lines are the root of the NBA chain's current-market data (2026-11 correction). A lines failure
# used to halt the whole chain (11 later steps skipped, including injuries and officiating, which do not
# need lines). Now a failed lines step is isolated: steps that genuinely need FRESH lines are reported
# SKIPPED_BLOCKED_BY_LINES, everything independent still runs, and the run exits non-zero (DEGRADED).
LINES_STEP = "game_lines"
LINES_SPORT_SLUG = "basketball_nba"

# Explicit dependency map: step -> (needs fresh game lines?, evidence). qc_game_lines_event_slate.py asserts
# every STEPS label is classified here.
STEP_LINES_DEPENDENCY = {
    "playoff_results": (False, "NBA results provider; runs before lines and never reads NBA_Odds"),
    "playoff_player_logs": (False, "player-log provider; runs before lines"),
    "game_lines": (False, "the lines step itself"),
    "player_props": (True, "DEPENDENT: fetch_player_props validates NBA props with validate_feed_slate, whose "
                           "independent eligible-event manifest is NBA_Odds.csv (SPORT_EVENT_MANIFESTS / "
                           "_eligible_event_keys). Without a fresh lines publish that manifest still lists "
                           "played games, so props coverage would be judged against the wrong slate."),
    "injuries": (False, "independent provider fetch (injury report); no odds/schedule input"),
    "basketball_officiating": (False, "independent provider fetch (officiating assignments)"),
    "officiating_context": (False, "rebuilds officiating context from data/context/*; no odds input"),
    "combined_prop_coverage": (False, "audit over the props files only; reports on whatever props are published"),
    "model_calibration": (False, "calibrates from graded NBA_AllPropResults.csv; no current lines input"),
    "runtime_snapshots": (True, "DEPENDENT: pre-renders NBA command-center/board snapshots that embed game "
                                "lines; snapshotting a stale lines file would freeze it as current"),
    "series_mappings_qc": (False, "QC: checks the published schedule; reports, never publishes"),
    "sources_qc": (False, "QC: checks the published sources; reports, never publishes"),
    "contradictions_qc": (False, "QC (--report-only) over the published board"),
    "board_qc": (False, "QC over the published board/schedule; reports, never publishes"),
}


def _lines_receipt_path() -> Path:
    return Path(BASE_DIR) / "data" / "tracking" / f"_last_game_lines_fetch_{LINES_SPORT_SLUG}.json"


def _lines_history_note() -> str:
    """LEGACY OPERATIONAL HISTORY ONLY: a one-liner from the shared, tokenless game-lines fetch receipt, printed
    beside a failed step for the operator. It never determines the stage outcome (that comes only from the
    stage's own per-run receipt -- services/nba_market.classify_stage)."""
    try:
        r = json.loads(_lines_receipt_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "history: no shared game-lines receipt"
    v = r.get("validation") or {}
    return (f"history only, last shared lines receipt: outcome={r.get('outcome')} reason={v.get('reason_code')} "
            f"run={str(r.get('run_id'))[:8]}")


STEPS = [
    ("playoff_results", [sys.executable, "-X", "utf8", "refresh_playoff_results.py"], 240),
    ("playoff_player_logs", [sys.executable, "-X", "utf8", "refresh_playoff_player_logs.py"], 480),
    # v5: the SHARED ensure API (services/nba_market.ensure_nba_lines) runs exactly this canonical stage
    # command (fetch_game_lines -> services.nba_lines_publisher): lock first, reuse a fresh verified publish
    # (e.g. the orchestrator's), else the one validated atomic publish. Timeout = lock wait + lines budget.
    ("game_lines", nba_market.stage_command("lines", NBA_DAILY_CALLER), budget.stage_timeout("lines")),
    # ensure_nba_props: its own lock first, reuse a verified props publish, verify the lines event list, else
    # the one validated publish. Timeout = lock wait + props budget.
    ("player_props", nba_market.stage_command("props", NBA_DAILY_CALLER), budget.stage_timeout("props")),
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
    lines_ok = True          # until the lines step runs and fails
    lines_exit = 0
    child_outcomes: dict[str, str] = {}
    step_results: dict[str, str] = {}
    for label, command, timeout in STEPS:
        needs_lines = STEP_LINES_DEPENDENCY.get(label, (True, "unclassified -> treated as dependent"))[0]
        if needs_lines and not lines_ok:
            # Honest skip: this step needs fresh game lines and the lines step failed THIS run.
            degraded = True
            step_results[label] = SKIPPED_BLOCKED_BY_LINES
            child_outcomes[label] = SKIPPED_BLOCKED_BY_LINES
            record_child_outcomes(BASE_DIR, "nba_daily", child_outcomes)
            print(f"[{SKIPPED_BLOCKED_BY_LINES}] {label}: {STEP_LINES_DEPENDENCY.get(label, ('', ''))[1]}",
                  flush=True)
            print()
            continue

        started = datetime.now()
        print(f"[STEP] {label} timeout={timeout}s", flush=True)

        if label == PROPS_STEP:
            # The shared ensure API (same command/policy/timeout as the orchestrator). Classified from the
            # publisher receipt, else the response-shape receipt (directive #2/#3). Benign -> continue
            # cleanly; alerting -> degrade the run but DO NOT abort the safe downstream steps.
            stage = nba_market.ensure_nba_props(NBA_DAILY_CALLER, base_dir=BASE_DIR, command=command,
                                                timeout=timeout, props_artifact=PROPS_ARTIFACT)
            elapsed = (datetime.now() - started).total_seconds()
            outcome, detail, alerting = stage["outcome"], stage["detail"], stage["alerting"]
            child_outcomes["player_props"] = outcome
            step_results[label] = outcome
            record_child_outcomes(BASE_DIR, "nba_daily", child_outcomes)
            print(f"[{outcome}] {label} seconds={elapsed:.1f} "
                  f"({'ALERT' if alerting else 'ok'}): {detail}", flush=True)
            if alerting:
                degraded = True
                print(f"[WARN] NBA props are {outcome}; continuing the rest of the NBA chain "
                      "(injuries/officiating/calibration/QC) and leaving the run DEGRADED.", flush=True)
            print()
            continue

        if label == LINES_STEP:
            # Isolated: a failed lines publish never aborts independent work; dependents skip honestly.
            stage = nba_market.ensure_nba_lines(NBA_DAILY_CALLER, base_dir=BASE_DIR, command=command,
                                                timeout=timeout)
            elapsed = (datetime.now() - started).total_seconds()
            outcome, detail, timed_out = stage["outcome"], stage["detail"], stage["timed_out"]
            child_outcomes["game_lines"] = outcome
            step_results[label] = outcome
            record_child_outcomes(BASE_DIR, "nba_daily", child_outcomes)
            if outcome not in LINES_READY:
                lines_ok = False
                lines_exit = 124 if timed_out else (int(stage["exit_code"]) or 1)
                degraded = True
                print()
                print(f"[{outcome}] {label} {'timed out' if timed_out else 'exited with code ' + str(stage['exit_code'])} "
                      f"after {elapsed:.1f}s: {detail} [{_lines_history_note()}]. Previous lines files "
                      "preserved; lines-dependent steps will be SKIPPED_BLOCKED_BY_LINES, independent steps "
                      "continue.", flush=True)
                print()
                continue
            print(f"[PASS] {label} seconds={elapsed:.1f} outcome={outcome}", flush=True)
            print()
            continue

        try:
            result = subprocess.run(command, timeout=timeout)
            timed_out = False
        except subprocess.TimeoutExpired:
            result = None
            timed_out = True
        elapsed = (datetime.now() - started).total_seconds()
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
            # An ungoverned child exit 1 becomes 2 (exit 1 is reserved for a governed benign outcome);
            # >=2 and signals stay hard failures.
            return runner_exit_for_child(result.returncode)
        step_results[label] = "PASS"
        print(f"[PASS] {label} seconds={elapsed:.1f}", flush=True)
        print()

    if not lines_ok:
        skipped = [k for k, v in step_results.items() if v == SKIPPED_BLOCKED_BY_LINES]
        print(f"NBA daily refresh is DEGRADED: game lines did not publish (exit {lines_exit}); "
              f"skipped as lines-dependent: {', '.join(skipped) or 'none'}. Independent steps completed.")
        # never the benign 1: a lines failure is a hard failure (>=2) whatever the child returned
        return runner_exit_for_child(lines_exit) if lines_exit else EXIT_HARD_FAILURE
    if degraded:
        print("NBA daily refresh completed the safe work but is DEGRADED (player props validation failed "
              "or unavailable for a non-benign reason).")
        return EXIT_HARD_FAILURE   # DEGRADED is a hard failure (>=2), never the benign 1
    print("NBA daily refresh completed cleanly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
