from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import pandas as pd
from pandas.errors import EmptyDataError

MINIMUM_SAMPLE = 10
LYING_THRESHOLD = 0.10
STRONG_THRESHOLD = 0.08


@dataclass
class BucketResult:
    bucket_type: str
    bucket_label: str
    sample_size: int
    expected_rate: float | None
    actual_rate: float | None
    gap: float | None
    classification: str
    recommendation: str


@dataclass
class CalibrationConfig:
    sport: str
    results_path: Path
    output_path: Path
    confidence_source_column: str
    default_method: str
    classify_rule_family: Callable[[str], str]
    role_signal_fn: Callable[[str], str]
    recommendation_fn: Callable[[str, str, float | None, int], str]


def safe_series(df: pd.DataFrame, column: str, default: str = "") -> pd.Series:
    if column in df.columns:
        return df[column].fillna(default).astype(str)
    return pd.Series([default] * len(df), index=df.index, dtype=str)


def confidence_band(value) -> str:
    score = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(score):
        return "Unknown"
    score = float(score)
    if score < 60:
        return "50-60"
    if score < 70:
        return "60-70"
    if score < 80:
        return "70-80"
    return "80+"


def expected_hit_rate(conf_band: str) -> float | None:
    mapping = {
        "50-60": 0.55,
        "60-70": 0.65,
        "70-80": 0.73,
        "80+": 0.81,
    }
    return mapping.get(str(conf_band or "").strip())


def classify_bucket(bucket_label: str, sample_size: int, actual_rate: float | None, expected_rate: float | None, recommendation_fn: Callable[[str, str, float | None, int], str]) -> tuple[str, str, float | None]:
    gap = None if actual_rate is None or expected_rate is None else actual_rate - expected_rate
    if sample_size < MINIMUM_SAMPLE:
        return "WATCH", f"Only {sample_size} resolved rows - monitor, do not adjust yet.", gap
    if actual_rate is None or expected_rate is None:
        return "INSUFFICIENT_SAMPLE", "No decisive rows yet.", gap
    if gap <= -LYING_THRESHOLD:
        return "LYING", recommendation_fn(bucket_label, "LYING", gap, sample_size), gap
    if gap >= STRONG_THRESHOLD:
        return "STRONG", recommendation_fn(bucket_label, "STRONG", gap, sample_size), gap
    return "CALIBRATED", "No action needed.", gap


def to_dataframe(buckets: list[BucketResult]) -> pd.DataFrame:
    if not buckets:
        return pd.DataFrame(columns=[
            "BucketType", "BucketLabel", "SampleSize", "ExpectedRate", "ActualRate", "Gap", "Classification", "Recommendation"
        ])
    return pd.DataFrame([{
        "BucketType": bucket.bucket_type,
        "BucketLabel": bucket.bucket_label,
        "SampleSize": bucket.sample_size,
        "ExpectedRate": bucket.expected_rate,
        "ActualRate": bucket.actual_rate,
        "Gap": bucket.gap,
        "Classification": bucket.classification,
        "Recommendation": bucket.recommendation,
    } for bucket in buckets])


def ranked_bucket_rows(df: pd.DataFrame, classification: str) -> list[dict]:
    if df.empty:
        return []
    filtered = df[df["Classification"] == classification].copy()
    if filtered.empty:
        return []
    filtered["AbsGap"] = filtered["Gap"].abs()
    filtered = filtered.sort_values(["AbsGap", "SampleSize"], ascending=[False, False], na_position="last")
    return filtered.to_dict("records")


def top_recommendations(lying_rows: list[dict], strong_rows: list[dict], limit: int = 3) -> list[str]:
    recommendations: list[str] = []
    for row in lying_rows + strong_rows:
        rec = str(row.get("Recommendation", "")).strip()
        if rec and rec not in recommendations:
            recommendations.append(rec)
        if len(recommendations) >= limit:
            break
    return recommendations


def format_rate(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{round(value * 100, 1)}%"


def format_gap(value: float | None) -> str:
    if value is None:
        return "-"
    pct = round(value * 100, 1)
    sign = "+" if pct > 0 else ""
    return f"{sign}{pct}%"


def default_role_signal(situations_text: str) -> str:
    text = str(situations_text or "").upper()
    if any(tag in text for tag in ["ROLE DOWN", "SHOT VOL-", "MIN-", "PROJ MIN-", "TREND MIN-", "SNAP MIN-"]):
        return "ROLE DOWN"
    if any(tag in text for tag in ["ROLE UP", "SHOT VOL+", "MIN+", "PROJ MIN+", "TREND MIN+", "SNAP MIN+"]):
        return "ROLE UP"
    return "STABLE"


def default_recommendation(bucket_label: str, classification: str, gap: float | None, sample_size: int) -> str:
    if sample_size < MINIMUM_SAMPLE:
        return f"Only {sample_size} resolved rows - monitor, do not adjust yet."
    if gap is None:
        return "No decisive rows yet."
    deficit = abs(gap)
    upper = bucket_label.upper()
    if classification == "LYING":
        if "OVER | NEGATIVE LINE MOVEMENT" in upper or "OVER | LINE MOVED AGAINST" in upper:
            return "Promote negative line-movement OVER gate to hard fail or HOLD."
        if deficit > 0.20:
            return "Cap confidence at the band floor until 20+ more resolved rows validate recovery."
        if deficit > 0.15:
            return "Add a manual-review gate for this bucket before it can be featured."
        return "Reduce this bucket's weight contribution by roughly 15% and monitor the next cycle."
    if classification == "STRONG":
        if gap > 0.15:
            return "Consider boosting this bucket's contribution by about 10%."
        return "Flag this bucket as high-trust support in scoring notes and keep tracking volume."
    return "No formula change recommended."


def normalize_results(raw: pd.DataFrame, config: CalibrationConfig) -> pd.DataFrame:
    working = raw.copy()
    working["OutcomeState"] = safe_series(working, "OutcomeState", "Pending")
    working["StatType"] = safe_series(working, "Stat", "").str.upper().replace("", "UNKNOWN")
    working["Direction"] = safe_series(working, "Direction", "").str.upper().replace("", "UNKNOWN")
    if config.confidence_source_column in working.columns:
        working["ConfidenceBand"] = working[config.confidence_source_column].apply(confidence_band)
    else:
        working["ConfidenceBand"] = pd.Series(["Unknown"] * len(working), index=working.index, dtype=str)
    working["PlayerTier"] = safe_series(working, "RoleLabel", "").replace("", "UNSPECIFIED")
    working["MarketGate"] = safe_series(working, "MarketGate", "").replace("", "CLEAR")
    if config.sport == "NFL":
        working["MarketGate"] = working["MarketGate"].replace("CLEAR", "")
        working.loc[working["MarketGate"].eq(""), "MarketGate"] = safe_series(working, "GovernanceTier", "").replace("", "CLEAR")
    working["WeightProfile"] = safe_series(working, "WeightProfile", "").replace("", "regular")
    if config.sport == "NFL":
        working["WeightProfile"] = working["WeightProfile"].replace("regular", "workbook")
    working["VolatilityFlag"] = safe_series(working, "VolatilityFlag", "").replace("", "STABLE")
    working["RoleSignal"] = safe_series(working, "Situations", "").apply(config.role_signal_fn)
    working["Method"] = safe_series(working, "Method", "").replace("", config.default_method)
    working["RuleFamily"] = safe_series(working, "Situations", "").apply(config.classify_rule_family)
    if config.sport == "NFL":
        governance_badge = safe_series(working, "GovernanceBadge", "")
        working["RuleFamily"] = governance_badge.where(governance_badge.ne(""), working["RuleFamily"])
    working["MarketMoveBucket"] = safe_series(working, "MarketMoveBucket", "").replace("", "Unknown")
    return working


def resolved_only(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["OutcomeState"].isin(["Hit", "Miss"])].copy()


def summarize_bucket(df: pd.DataFrame, label: str, config: CalibrationConfig) -> BucketResult:
    sample_size = int(len(df))
    conf_band = str(df["ConfidenceBand"].mode().iloc[0]) if "ConfidenceBand" in df.columns and not df.empty else "Unknown"
    expected_rate = expected_hit_rate(conf_band)
    actual_rate = float(df["OutcomeState"].eq("Hit").mean()) if sample_size else None
    classification, recommendation, gap = classify_bucket(label, sample_size, actual_rate, expected_rate, config.recommendation_fn)
    return BucketResult("", label, sample_size, expected_rate, actual_rate, gap, classification, recommendation)


def build_bucket_results(df: pd.DataFrame, config: CalibrationConfig) -> list[BucketResult]:
    buckets: list[BucketResult] = []

    def add_group(bucket_type: str, columns: list[str]) -> None:
        if df.empty:
            return
        for key, group in df.groupby(columns, dropna=False):
            if not isinstance(key, tuple):
                key = (key,)
            label = " | ".join(str(part or "Unknown") for part in key)
            result = summarize_bucket(group, label, config)
            result.bucket_type = bucket_type
            buckets.append(result)

    add_group("StatType", ["StatType"])
    add_group("Direction", ["Direction"])
    add_group("ConfidenceBand", ["ConfidenceBand"])
    add_group("PlayerTier", ["PlayerTier"])
    add_group("MarketGate", ["MarketGate"])
    add_group("WeightProfile", ["WeightProfile"])
    add_group("VolatilityFlag", ["VolatilityFlag"])
    add_group("RoleSignal", ["RoleSignal"])
    add_group("Method", ["Method"])
    add_group("RuleFamily", ["RuleFamily"])
    add_group("StatType + Direction + ConfidenceBand", ["StatType", "Direction", "ConfidenceBand"])
    add_group("StatType + Direction + PlayerTier", ["StatType", "Direction", "PlayerTier"])
    add_group("StatType + Direction + RoleSignal", ["StatType", "Direction", "RoleSignal"])
    add_group("Direction + VolatilityFlag + MarketGate", ["Direction", "VolatilityFlag", "MarketGate"])
    add_group("Direction + MarketMoveBucket", ["Direction", "MarketMoveBucket"])
    add_group("WeightProfile + Direction", ["WeightProfile", "Direction"])
    add_group("Method + Direction", ["Method", "Direction"])
    return buckets


def run_calibration(config: CalibrationConfig) -> dict:
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    config.output_path.parent.mkdir(parents=True, exist_ok=True)
    if not config.results_path.exists():
        to_dataframe([]).to_csv(config.output_path, index=False)
        report = {
            "checked_at": checked_at,
            "clean": True,
            "pass_count": 0,
            "warning_count": 0,
            "failure_count": 0,
            "notes": f"No {config.sport} featured-results file available for calibration.",
            "resolved_rows": 0,
            "pending_rows": 0,
            "overall_hit_rate": None,
            "lying_buckets": [],
            "strong_buckets": [],
            "watch_buckets": [],
            "top_recommendations": [],
            "report_path": str(config.output_path),
        }
        return report

    try:
        raw = pd.read_csv(config.results_path)
    except EmptyDataError:
        to_dataframe([]).to_csv(config.output_path, index=False)
        return {
            "checked_at": checked_at,
            "clean": True,
            "pass_count": 0,
            "warning_count": 0,
            "failure_count": 0,
            "notes": f"No {config.sport} rows available for calibration.",
            "resolved_rows": 0,
            "pending_rows": 0,
            "overall_hit_rate": None,
            "lying_buckets": [],
            "strong_buckets": [],
            "watch_buckets": [],
            "top_recommendations": [],
            "report_path": str(config.output_path),
        }
    if raw.empty:
        to_dataframe([]).to_csv(config.output_path, index=False)
        return {
            "checked_at": checked_at,
            "clean": True,
            "pass_count": 0,
            "warning_count": 0,
            "failure_count": 0,
            "notes": f"No {config.sport} rows available for calibration.",
            "resolved_rows": 0,
            "pending_rows": 0,
            "overall_hit_rate": None,
            "lying_buckets": [],
            "strong_buckets": [],
            "watch_buckets": [],
            "top_recommendations": [],
            "report_path": str(config.output_path),
        }

    working = normalize_results(raw, config)
    pending_rows = int((working["OutcomeState"] == "Pending").sum())
    resolved = resolved_only(working)
    overall_hit_rate = float(resolved["OutcomeState"].eq("Hit").mean()) if not resolved.empty else None
    buckets = build_bucket_results(resolved, config)
    bucket_df = to_dataframe(buckets)
    config.output_path.parent.mkdir(parents=True, exist_ok=True)
    bucket_df.to_csv(config.output_path, index=False)

    lying_rows = ranked_bucket_rows(bucket_df, "LYING")
    strong_rows = ranked_bucket_rows(bucket_df, "STRONG")
    watch_rows = ranked_bucket_rows(bucket_df, "WATCH")

    return {
        "checked_at": checked_at,
        "clean": True,
        "pass_count": int(len(resolved)),
        "warning_count": int(len(watch_rows)),
        "failure_count": int(len(lying_rows)),
        "notes": (
            f"Resolved {len(resolved)} {config.sport} rows. "
            f"Lying buckets: {len(lying_rows)}. Strong buckets: {len(strong_rows)}."
        ),
        "resolved_rows": int(len(resolved)),
        "pending_rows": pending_rows,
        "overall_hit_rate": round(overall_hit_rate * 100, 1) if overall_hit_rate is not None else None,
        "lying_buckets": lying_rows,
        "strong_buckets": strong_rows,
        "watch_buckets": watch_rows,
        "top_recommendations": top_recommendations(lying_rows, strong_rows),
        "report_path": str(config.output_path),
    }


def print_bucket_section(title: str, rows: list[dict], limit: int = 12) -> None:
    print(title)
    if not rows:
        print("  (none)")
        print()
        return
    for row in rows[:limit]:
        print(f"{row['BucketLabel']}")
        print(f"  Sample:    {int(row['SampleSize'])} resolved")
        print(f"  Expected:  {format_rate(row.get('ExpectedRate'))}")
        print(f"  Actual:    {format_rate(row.get('ActualRate'))}")
        print(f"  Gap:       {format_gap(row.get('Gap'))}")
        print(f"  -> RECOMMENDATION: {row.get('Recommendation')}")
        print()


def print_report(title: str, report: dict) -> None:
    print("=" * 54)
    print(title)
    print("=" * 54)
    print(f"Resolved rows:     {report.get('resolved_rows', 0)}")
    print(f"Pending rows:      {report.get('pending_rows', 0)}")
    print(f"Overall hit rate:  {report.get('overall_hit_rate') if report.get('overall_hit_rate') is not None else '-'}%")
    print(f"Bucket report:     {report.get('report_path')}")
    print()
    print_bucket_section("[LYING BUCKETS]", report.get("lying_buckets", []))
    print_bucket_section("[STRONG BUCKETS]", report.get("strong_buckets", []))
    print_bucket_section("[WATCH BUCKETS]", report.get("watch_buckets", []), limit=8)
    print("=" * 54)
    print("TOP 3 FORMULA CHANGES RECOMMENDED THIS CYCLE")
    print("=" * 54)
    recommendations = report.get("top_recommendations", [])
    if not recommendations:
        print("No calibration changes recommended yet.")
    else:
        for idx, item in enumerate(recommendations[:3], start=1):
            print(f"{idx}. {item}")
    print("=" * 54)
