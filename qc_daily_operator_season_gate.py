"""QC: the daily operator season-gates NFL preseason jobs (Oct 23 incident class).

The operator aborts on the first FAIL, so a single out-of-window step that hard-FAILs stalls every
downstream refresh. The NFL preseason lines step fetches the preseason Odds sport key, which has no
events outside ~Aug; because the regular-season gate keys on NFL_Props.csv (populated in-season), that
preseason step is NOT treated as off-season NFL in October -- so an erroring out-of-window fetch would
abort the whole run. This guard proves the preseason window helper + that the operator's step list
still contains a label the preseason gate matches, so the SKIP path actually applies.

Pure (no app / network / Flask). Exits 0 when the gate holds, 1 otherwise.
"""
from __future__ import annotations

from datetime import date

import run_daily
from season_utils import is_preseason_step, nfl_preseason_active


def run_qc():
    issues, notes = [], []

    # (1) preseason window boundaries
    window_cases = [
        (date(2026, 10, 23), False, "Oct 23 (the incident date) -> closed"),
        (date(2026, 1, 1), False, "Jan -> closed"),
        (date(2026, 7, 19), False, "Jul 19 -> closed (before window)"),
        (date(2026, 7, 20), True, "Jul 20 -> open (HOF game era)"),
        (date(2026, 8, 15), True, "mid-Aug -> open"),
        (date(2026, 9, 12), True, "Sep 12 -> open (final preseason week)"),
        (date(2026, 9, 13), False, "Sep 13 -> closed (regular season)"),
    ]
    for d, want, desc in window_cases:
        got = nfl_preseason_active(d)
        if got != want:
            issues.append(f"nfl_preseason_active({d}) = {got}, want {want} ({desc})")
        else:
            notes.append(f"{desc}: {got}")

    # (2) label classification
    if not is_preseason_step("NFL preseason lines"):
        issues.append("is_preseason_step did not match the 'NFL preseason lines' label")
    if is_preseason_step("NFL first-half lines"):
        issues.append("is_preseason_step wrongly matched a non-preseason label")

    # (3) the operator's step list still contains a preseason-gated step (so the SKIP path applies).
    steps = run_daily._active_refresh_steps({"nba", "wnba", "mlb"})
    preseason_steps = [lbl for (lbl, _cmd, _to) in steps if is_preseason_step(lbl)]
    if not preseason_steps:
        issues.append("no preseason-gated step found in the operator chain -- the preseason gate "
                      "matches nothing (was the step renamed so 'PRESEASON' no longer appears?)")
    else:
        notes.append(f"preseason-gated step(s) present: {preseason_steps}")
        # (4) on the incident date, every preseason step is pre-skipped (never run, never FAIL).
        if nfl_preseason_active(date(2026, 10, 23)):
            issues.append("preseason window reported OPEN on Oct 23 -- preseason step would run/FAIL")
        else:
            notes.append("Oct 23: preseason step(s) are SKIPPED, not run -> cannot abort the operator")

    if not issues:
        notes.append("NFL preseason jobs are season-gated (SKIP out of window, never FAIL)")
    return {"issues": issues, "notes": notes}


def main() -> int:
    report = run_qc()
    print("=" * 60)
    print("BANKROLL KINGS DAILY OPERATOR SEASON-GATE QC")
    print("=" * 60)
    for n in report["notes"]:
        print(f"[NOTE] {n}")
    if report["notes"]:
        print()
    if not report["issues"]:
        print("Daily operator season-gate verified.")
        return 0
    for m in report["issues"]:
        print(f"[FAIL] {m}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
