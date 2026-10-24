"""
QC for services/run_outcomes.py -- the per-sport outcome classifier (incident 2026-10-24 #2/#3).

Proves the vocabulary mapping, and in particular the directive-#2 rule: zero output rows is
VALIDATION_FAILED unless the response-shape receipt PROVES no requested market was posted on any
event. A benign NO_MARKETS_POSTED is only reached with that proof.
"""
from __future__ import annotations

from services.run_outcomes import (
    NO_ACTIVE_EVENTS, NO_MARKETS_POSTED, PROVIDER_ERROR, STALE, UPDATED, VALIDATION_FAILED,
    aggregate_parent, classify_props_child, is_alerting,
)


def _receipt(events, rows, present, errors=0, proven=None):
    if proven is None:
        proven = bool(events > 0 and errors == 0 and rows == 0 and not present)
    return {
        "events_found": events,
        "rows_fetched": rows,
        "provider_error_count": errors,
        "markets_present_anywhere": present,
        "shape_proves_no_markets_posted": proven,
    }


def main() -> int:
    f = []
    cases = [
        # (name, exit_code, advanced, receipt, expected)
        ("updated", 0, True, _receipt(9, 540, ["player_points"]), UPDATED),
        ("no_active_events", 1, False, _receipt(0, 0, []), NO_ACTIVE_EVENTS),
        # THE NBA case: 9 events, 0 rows, NO market present anywhere, no errors -> proven benign.
        ("no_markets_proven", 1, False, _receipt(9, 0, [], errors=0), NO_MARKETS_POSTED),
        # 9 events, 0 rows, but a requested market WAS present -> NOT proven -> VALIDATION_FAILED (#2).
        ("zero_rows_markets_present", 1, False, _receipt(9, 0, ["player_points"], proven=False), VALIDATION_FAILED),
        # 9 events, 0 rows, provider errors -> PROVIDER_ERROR, not NO_MARKETS_POSTED.
        ("provider_error", 1, False, _receipt(9, 0, [], errors=4), PROVIDER_ERROR),
        # rows fetched but artifact did not advance -> collapse/validation preserved prior.
        ("fetched_not_published", 1, False, _receipt(9, 12, ["player_points"]), VALIDATION_FAILED),
        # no receipt at all: success+advanced=UPDATED, success+not-advanced=STALE, failure=VALIDATION_FAILED.
        ("no_receipt_ok", 0, True, None, UPDATED),
        ("no_receipt_no_advance", 0, False, None, STALE),
        ("no_receipt_fail", 1, False, None, VALIDATION_FAILED),
    ]
    for name, code, adv, rec, expected in cases:
        got, _ = classify_props_child(code, adv, rec)
        if got != expected:
            f.append(f"{name}: expected {expected}, got {got}")

    # the critical anti-inference assertion: 0 rows + 0 cost-looking receipt but unproven -> NOT benign.
    got, _ = classify_props_child(1, False, _receipt(9, 0, ["player_rebounds"], proven=False))
    if got != VALIDATION_FAILED or not is_alerting(got):
        f.append(f"unproven zero-rows must be alerting VALIDATION_FAILED, got {got}")

    # aggregate: any alerting child => degraded; all benign => not degraded.
    _, degraded = aggregate_parent({"nfl": NO_MARKETS_POSTED, "ncaaf": VALIDATION_FAILED})
    if not degraded:
        f.append("a VALIDATION_FAILED child must degrade the parent")
    _, degraded2 = aggregate_parent({"nfl": NO_MARKETS_POSTED, "ncaaf": NO_ACTIVE_EVENTS})
    if degraded2:
        f.append("all-benign children must not degrade the parent")

    print("=" * 60)
    print("QC: RUN OUTCOMES CLASSIFIER")
    print("=" * 60)
    if f:
        for x in f:
            print(f"[FAIL] {x}")
        return 1
    print("[OK] vocabulary + the directive-#2 'VALIDATION_FAILED until proven' rule hold.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
