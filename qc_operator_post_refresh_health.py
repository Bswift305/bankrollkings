"""
QC (Oct-24 follow-up #2): the daily operator must not leave a PRE-refresh Odds-feed-health failure
recorded as a blocking failure once the run's refreshes make the feeds current. The pre-refresh check
is a WARNING; the authoritative signal is a POST-refresh health check run after every refresh.

Proven offline by faking run_daily._run_step (no real subprocess):
  A. pre-refresh health FAILS but post-refresh PASSES (recovery) -> operator NOT blocked by health; the
     pre-refresh step is WARN and neither health label is a blocking failed_step.
  B. pre-refresh FAILS and post-refresh FAILS (feed still stale, e.g. NBA) -> blocking; only the
     POST-refresh label is the failed_step, never the pre-refresh one.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import run_daily


def _run(scenario_post_ok: bool):
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "logs").mkdir(parents=True, exist_ok=True)
        (base / "data" / "tracking").mkdir(parents=True, exist_ok=True)
        orig_base, orig_log = run_daily.BASE_DIR, run_daily.LOG_DIR
        run_daily.BASE_DIR = base
        run_daily.LOG_DIR = base / "logs"

        def fake_run(label, command, timeout):
            if label == "Odds feed health":
                return False, "NBA props STALE (pre-refresh snapshot)"
            if label == "Odds feed health (post-refresh)":
                return (scenario_post_ok, "" if scenario_post_ok else "NBA props STALE (post-refresh)")
            return True, ""  # every other step passes

        orig_step = run_daily._run_step
        run_daily._run_step = fake_run
        orig_argv = sys.argv
        sys.argv = ["run_daily.py", "--sports", "wnba", "--skip-edge", "--skip-scorecards",
                    "--continue-on-error"]
        try:
            rc = run_daily.main()
        finally:
            run_daily._run_step = orig_step
            run_daily.BASE_DIR, run_daily.LOG_DIR = orig_base, orig_log
            sys.argv = orig_argv
        summary = json.loads((base / "data/tracking/Last_Operator_Summary.json").read_text(encoding="utf-8"))
        return rc, summary


def main() -> int:
    f = []

    # A. recovery: post-refresh passes
    rc_a, sa = _run(scenario_post_ok=True)
    pre_a = next((s for s in sa["steps"] if s["label"] == "Odds feed health"), None)
    if not pre_a or "WARN" not in pre_a["status"]:
        f.append(f"A: pre-refresh health should be WARN, got {pre_a}")
    if "Odds feed health" in sa["failed_steps"]:
        f.append("A: a recovered pre-refresh warning must NOT be a blocking failed_step")
    if "Odds feed health (post-refresh)" in sa["failed_steps"]:
        f.append("A: post-refresh passed, so it must not be a failed_step")
    if sa["blocking_failure"]:
        f.append(f"A: no blocking failure expected on full recovery; got failed_steps={sa['failed_steps']}")

    # B. still stale: post-refresh fails
    rc_b, sb = _run(scenario_post_ok=False)
    if "Odds feed health" in sb["failed_steps"]:
        f.append("B: the PRE-refresh label must never be the blocking failure")
    if "Odds feed health (post-refresh)" not in sb["failed_steps"]:
        f.append(f"B: the POST-refresh label must be the blocking failure; got {sb['failed_steps']}")
    if not sb["blocking_failure"]:
        f.append("B: a still-stale feed post-refresh must block")

    print("=" * 64)
    print("QC: OPERATOR POST-REFRESH HEALTH (final-state, not pre-refresh)")
    print("=" * 64)
    if f:
        for x in f:
            print(f"[FAIL] {x}")
        return 1
    print("[OK] pre-refresh health is a non-blocking WARN; the post-refresh check is authoritative.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
