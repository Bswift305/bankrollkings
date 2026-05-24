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


def nba_recommendation(bucket_label: str, classification: str, gap: float | None, sample_size: int) -> str:
    if sample_size < 10:
        return f"Only {sample_size} resolved rows - monitor, do not adjust yet."
    if gap is None:
        return "No decisive rows yet."
    upper = bucket_label.upper()
    if classification == "LYING":
        if "BLK | OVER" in upper:
            return "Cap BLK OVER confidence at 60 and consider a dedicated contradiction rule."
        if "AST | OVER | SUPPORT" in upper:
            return "Reduce SUPPORT AST OVER ceiling or add a support-role contradiction check."
    if classification == "STRONG":
        if "UNDER | STABLE | CLEAR" in upper:
            return "Boost featured weight for stable CLEAR unders and raise the confidence ceiling modestly."
        if "AST | OVER | ROLE UP" in upper:
            return "Reduce AST OVER penalty for ROLE-UP players; this bucket is outperforming the current read."
    return default_recommendation(bucket_label, classification, gap, sample_size)


def main() -> int:
    config = CalibrationConfig(
        sport="NBA",
        results_path=BASE_DIR / "data" / "tracking" / "NBA_AllPropResults.csv",
        output_path=BASE_DIR / "data" / "tracking" / "NBA_Calibration_Report.csv",
        confidence_source_column="Confidence",
        default_method="Featured Top Play",
        classify_rule_family=classify_featured_rule_family,
        role_signal_fn=default_role_signal,
        recommendation_fn=nba_recommendation,
    )
    report = run_calibration(config)
    append_qc_run_log("nba_model_calibration", report)
    print_report("NBA MODEL CALIBRATION REPORT", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
