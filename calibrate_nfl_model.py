from __future__ import annotations

from pathlib import Path

from services.model_calibration import (
    CalibrationConfig,
    default_recommendation,
    default_role_signal,
    print_report,
    run_calibration,
)
from services.qc_tracking import append_qc_run_log


BASE_DIR = Path(__file__).resolve().parent


def nfl_rule_family(text: str) -> str:
    upper = str(text or "").upper()
    if "REVIEW TIGHT" in upper:
        return "REVIEW TIGHT"
    if "PARTIAL" in upper:
        return "PARTIAL SUPPORT"
    if "FADE" in upper:
        return "FADE"
    return "BASE"


def nfl_recommendation(bucket_label: str, classification: str, gap: float | None, sample_size: int) -> str:
    if sample_size < 10:
        return f"Only {sample_size} resolved rows - monitor, do not adjust yet."
    if gap is None:
        return "No decisive rows yet."
    upper = bucket_label.upper()
    if classification == "LYING":
        if "REC YDS" in upper and "REVIEW TIGHT" in upper:
            return "Promote tight-support receiver-yard warnings to a harder contradiction rule if this persists."
        if "RUSH YDS" in upper or "PASS YDS" in upper:
            return "Reduce trust score on yardage props for this bucket and require stronger support."
    if classification == "STRONG":
        if "RECEPTIONS" in upper:
            return "Keep receptions buckets as supported/high-trust when review continues to confirm them."
    return default_recommendation(bucket_label, classification, gap, sample_size)


def main() -> int:
    config = CalibrationConfig(
        sport="NFL",
        results_path=BASE_DIR / "data" / "tracking" / "NFL_AllPropResults.csv",
        output_path=BASE_DIR / "data" / "tracking" / "NFL_Calibration_Report.csv",
        confidence_source_column="Confidence",
        default_method="NFL Historical Backfill",
        classify_rule_family=nfl_rule_family,
        role_signal_fn=default_role_signal,
        recommendation_fn=nfl_recommendation,
    )
    report = run_calibration(config)
    append_qc_run_log("nfl_model_calibration", report)
    print_report("NFL MODEL CALIBRATION REPORT", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
