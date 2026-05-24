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


def cfb_recommendation(bucket_label: str, classification: str, gap: float | None, sample_size: int) -> str:
    upper = bucket_label.upper()
    if classification == "LYING" and "PROPS" in upper:
        return "Keep CFB props as optional support only until a larger sample proves this bucket can lead."
    return default_recommendation(bucket_label, classification, gap, sample_size)


def main() -> int:
    config = CalibrationConfig(
        sport="NCAAF",
        results_path=BASE_DIR / "data" / "tracking" / "NCAAF_FeaturedResults.csv",
        output_path=BASE_DIR / "data" / "tracking" / "NCAAF_Calibration_Report.csv",
        confidence_source_column="Confidence",
        default_method="Featured Top Play",
        classify_rule_family=classify_featured_rule_family,
        role_signal_fn=default_role_signal,
        recommendation_fn=cfb_recommendation,
    )
    report = run_calibration(config)
    append_qc_run_log("ncaaf_model_calibration", report)
    print_report("NCAAF MODEL CALIBRATION REPORT", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
