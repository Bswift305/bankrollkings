from __future__ import annotations

from pathlib import Path

from app import classify_featured_rule_family
from services.model_calibration import (
    CalibrationConfig,
    default_recommendation,
    default_role_signal,
    print_report,
    run_calibration,
)
from services.qc_tracking import append_qc_run_log


BASE_DIR = Path(__file__).resolve().parent


def mlb_recommendation(bucket_label: str, classification: str, gap: float | None, sample_size: int) -> str:
    if sample_size < 10:
        return f"Only {sample_size} resolved rows - monitor, do not adjust yet."
    if gap is None:
        return "No decisive rows yet."
    upper = bucket_label.upper()
    if classification == "LYING":
        if "UNDER | STABLE | CLEAR" in upper:
            return "This conservative under profile is underperforming the model; add a caution gate until more data accumulates."
        if "TOTAL BASES | OVER" in upper:
            return "Cap Total Bases OVER confidence until the hit rate catches up."
    if classification == "STRONG":
        if "PITCHER KS | UNDER" in upper:
            return "Pitcher Ks unders are outperforming here; consider a modest boost."
        if "HITS | OVER" in upper:
            return "Hits overs are validating the read; keep this bucket on the trust list."
    return default_recommendation(bucket_label, classification, gap, sample_size)


def main() -> int:
    config = CalibrationConfig(
        sport="MLB",
        results_path=BASE_DIR / "data" / "tracking" / "MLB_AllPropResults.csv",
        output_path=BASE_DIR / "data" / "tracking" / "MLB_Calibration_Report.csv",
        confidence_source_column="Confidence",
        default_method="Main Board",
        classify_rule_family=classify_featured_rule_family,
        role_signal_fn=default_role_signal,
        recommendation_fn=mlb_recommendation,
    )
    report = run_calibration(config)
    append_qc_run_log("mlb_model_calibration", report)
    print_report("MLB MODEL CALIBRATION REPORT", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
