"""QC: retrospective calibration/promotion context cannot mutate live scores or ordering keys."""
from __future__ import annotations

from copy import deepcopy
from unittest import mock

import app as web


def qc_calibration_is_context_only():
    rows = [{"player": "A", "stat": "RUSH YDS", "direction": "OVER",
             "method_score": 70.0, "market_confidence": 61.0, "method_tags": []}]
    adjustments = [{"bucket_type": "Direction", "bucket_label": "OVER", "sample_size": 100,
                    "gap": .20, "classification": "STRONG", "recommendation": ""}]
    with mock.patch.object(web, "_load_live_calibration_adjustments", return_value=adjustments):
        out = web.apply_live_calibration_adjustments(deepcopy(rows), "NFL")[0]
    ok = (out["method_score"] == 70.0 and out["market_confidence"] == 61.0 and
          out["calibration_adjustment"] == 0.0 and out["calibration_context_delta"] == 5.0 and
          out["calibration_authority"] == "RESEARCH_ONLY" and
          "CALIBRATION CONTEXT" in out["method_tags"])
    return ok, str(out)


def qc_promotion_is_context_only():
    rows = [{"player": "A", "sport": "NFL", "stat": "RUSH YDS", "direction": "OVER",
             "method_score": 70.0, "market_confidence": 61.0, "build_quality_score": 75.0}]
    context = {"profiles": {}, "bucket_frequency": {}}
    signal = {"signal": "PROMOTE HARD", "reason": "retrospective row", "action": "surface",
              "missed_count": 2, "bucket_a_plus": 1, "bucket_avg_grade": 88, "last_seen": "2026-10-17"}
    with mock.patch.object(web, "_build_live_promotion_signal_context", return_value=context), \
         mock.patch.object(web, "calculate_promotion_signal_service", return_value=signal):
        out = web.attach_promotion_signals_to_props(deepcopy(rows), sport="NFL")[0]
    ok = (out["method_score"] == 70.0 and out["market_confidence"] == 61.0 and
          out["build_quality_score"] == 75.0 and out["promotion_boost"] == 0.0 and
          out["promotion_context_delta"] == 4.5 and out["promotion_signal"] == "RESEARCH CONTEXT" and
          out["promotion_research_signal"] == "PROMOTE HARD" and
          out["promotion_authority"] == "RESEARCH_ONLY")
    return ok, str(out)


def qc_order_is_unchanged():
    rows = [
        {"player": "Higher", "sport": "NFL", "stat": "RUSH YDS", "direction": "OVER", "method_score": 80.0},
        {"player": "Lower", "sport": "NFL", "stat": "RUSH YDS", "direction": "OVER", "method_score": 60.0},
    ]
    signals = iter([
        {"signal": "HOLD", "reason": "", "action": "", "missed_count": 0},
        {"signal": "PROMOTE HARD", "reason": "", "action": "", "missed_count": 0},
    ])
    with mock.patch.object(web, "_build_live_promotion_signal_context",
                           return_value={"profiles": {}, "bucket_frequency": {}}), \
         mock.patch.object(web, "calculate_promotion_signal_service", side_effect=lambda *_: next(signals)):
        out = web.attach_promotion_signals_to_props(deepcopy(rows), sport="NFL")
    ordered = [r["player"] for r in sorted(out, key=lambda r: (r["promotion_boost"], r["method_score"]), reverse=True)]
    ok = ordered == ["Higher", "Lower"] and all(r["promotion_boost"] == 0 for r in out)
    return ok, str(ordered)


CHECKS = [
    ("calibration context cannot mutate score", qc_calibration_is_context_only),
    ("promotion context cannot mutate score", qc_promotion_is_context_only),
    ("promotion label cannot reorder", qc_order_is_unchanged),
]


def main():
    failures = 0
    for label, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        print(f"[{'PASS' if ok else 'FAIL'}] {label}: {detail}")
        failures += int(not ok)
    print(f"Unqualified Authority Containment QC: {len(CHECKS) - failures}/{len(CHECKS)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
