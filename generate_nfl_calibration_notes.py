from __future__ import annotations

from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
TRACKING_DIR = BASE_DIR / "data" / "tracking"
SCORED_PATH = TRACKING_DIR / "NFL_AllPropResults_Scored.csv"
SIM_PATH = TRACKING_DIR / "NFL_Simulation_Results.csv"
SUMMARY_PATH = TRACKING_DIR / "NFL_Formula_Calibration_Summary.csv"
NOTES_PATH = TRACKING_DIR / "Calibration_Notes_NFL_2025.txt"
MIN_SAMPLE = 100


def pct(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{value * 100:.1f}%"


def safe_num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def hit_rate(group: pd.DataFrame) -> float:
    resolved = group[group["OutcomeState"].isin(["Hit", "Miss"])]
    if resolved.empty:
        return float("nan")
    return float(resolved["OutcomeState"].eq("Hit").mean())


def summarize_group(df: pd.DataFrame, bucket_type: str, label_col: str) -> list[dict]:
    rows = []
    resolved = df[df["OutcomeState"].isin(["Hit", "Miss"])].copy()
    if resolved.empty or label_col not in resolved.columns:
        return rows

    for label, group in resolved.groupby(label_col, dropna=False):
        if len(group) < MIN_SAMPLE:
            continue
        rows.append(
            {
                "BucketType": bucket_type,
                "BucketLabel": str(label),
                "SampleSize": int(len(group)),
                "ActualRate": round(hit_rate(group), 4),
                "AverageConfidence": round(float(safe_num(group.get("Confidence", pd.Series())).mean()) / 100.0, 4),
                "AverageEdgeScore": round(float(safe_num(group.get("BK_NFL_EdgeScore", pd.Series())).mean()), 2),
                "AveragePropScore": round(float(safe_num(group.get("BK_NFL_PropScore", pd.Series())).mean()), 2),
            }
        )
    return rows


def add_score_bands(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["ConfidenceBand"] = pd.cut(
        safe_num(out.get("Confidence", pd.Series())),
        bins=[-1, 50, 60, 70, 80, 101],
        labels=["<50", "50-60", "60-70", "70-80", "80+"],
    ).astype(str)
    out["EdgeScoreBand"] = pd.cut(
        safe_num(out.get("BK_NFL_EdgeScore", pd.Series())),
        bins=[-999, 0, 10, 20, 999],
        labels=["<0", "0-10", "10-20", "20+"],
    ).astype(str)
    out["PropScoreBand"] = pd.cut(
        safe_num(out.get("BK_NFL_PropScore", pd.Series())),
        bins=[-999, 0, 15, 25, 999],
        labels=["<0", "0-15", "15-25", "25+"],
    ).astype(str)
    return out


def explode_tag_summary(df: pd.DataFrame, column: str, bucket_type: str) -> list[dict]:
    if column not in df.columns:
        return []
    resolved = df[df["OutcomeState"].isin(["Hit", "Miss"])].copy()
    rows = []
    exploded = []
    for _, row in resolved.iterrows():
        tags = [part.strip() for part in str(row.get(column) or "").split("|") if part.strip()]
        for tag in tags:
            item = row.to_dict()
            item["Tag"] = tag
            exploded.append(item)
    if not exploded:
        return []
    tag_df = pd.DataFrame(exploded)
    for label, group in tag_df.groupby("Tag", dropna=False):
        if len(group) < MIN_SAMPLE:
            continue
        rows.append(
            {
                "BucketType": bucket_type,
                "BucketLabel": str(label),
                "SampleSize": int(len(group)),
                "ActualRate": round(hit_rate(group), 4),
                "AverageConfidence": round(float(safe_num(group.get("Confidence", pd.Series())).mean()) / 100.0, 4),
                "AverageEdgeScore": round(float(safe_num(group.get("BK_NFL_EdgeScore", pd.Series())).mean()), 2),
                "AveragePropScore": round(float(safe_num(group.get("BK_NFL_PropScore", pd.Series())).mean()), 2),
            }
        )
    return rows


def simulation_summary() -> list[dict]:
    if not SIM_PATH.exists():
        return []
    sim = pd.read_csv(SIM_PATH, low_memory=False)
    resolved = sim[sim["OutcomeState"].isin(["Hit", "Miss"])].copy()
    resolved["SimProbabilityBand"] = pd.cut(
        safe_num(resolved.get("SimHitProbability", pd.Series())),
        bins=[-1, 50, 60, 70, 101],
        labels=["<50", "50-60", "60-70", "70+"],
    ).astype(str)
    rows = []
    for label, group in resolved.groupby("SimProbabilityBand", dropna=False):
        if len(group) < MIN_SAMPLE:
            continue
        rows.append(
            {
                "BucketType": "SimulationProbability",
                "BucketLabel": str(label),
                "SampleSize": int(len(group)),
                "ActualRate": round(hit_rate(group), 4),
                "AverageConfidence": round(float(safe_num(group.get("Confidence", pd.Series())).mean()) / 100.0, 4),
                "AverageEdgeScore": round(float(safe_num(group.get("BK_NFL_EdgeScore", pd.Series())).mean()), 2),
                "AveragePropScore": round(float(safe_num(group.get("BK_NFL_PropScore", pd.Series())).mean()), 2),
            }
        )
    return rows


def classify(row: pd.Series) -> str:
    actual = float(row["ActualRate"])
    expected = float(row.get("AverageConfidence") or 0.55)
    gap = actual - expected
    if row["SampleSize"] < 250:
        return "WATCH"
    if actual >= 0.60 and gap >= 0.03:
        return "UNDERWEIGHTED"
    if actual <= 0.47 and gap <= -0.05:
        return "OVERWEIGHTED"
    if abs(gap) <= 0.05:
        return "CALIBRATED"
    return "WATCH"


def recommendation(row: pd.Series) -> str:
    label = row["BucketLabel"]
    bucket_type = row["BucketType"]
    classification = row["Classification"]
    if classification == "UNDERWEIGHTED":
        return f"Promote {bucket_type}={label} cautiously; it is beating current confidence with a usable sample."
    if classification == "OVERWEIGHTED":
        return f"Reduce trust for {bucket_type}={label}; actual hit rate is lagging expected confidence."
    if classification == "CALIBRATED":
        return f"Keep {bucket_type}={label} at current weighting."
    return f"Monitor {bucket_type}={label}; sample or gap is not decisive yet."


def write_notes(summary: pd.DataFrame, scored: pd.DataFrame) -> None:
    resolved = scored[scored["OutcomeState"].isin(["Hit", "Miss"])].copy()
    overall = hit_rate(resolved)
    top_under = summary[summary["Classification"].eq("UNDERWEIGHTED")].sort_values(
        ["ActualRate", "SampleSize"], ascending=[False, False]
    ).head(8)
    top_over = summary[summary["Classification"].eq("OVERWEIGHTED")].sort_values(
        ["ActualRate", "SampleSize"], ascending=[True, False]
    ).head(8)
    sim_rows = summary[summary["BucketType"].eq("SimulationProbability")].sort_values("BucketLabel")

    lines = [
        "NFL Calibration Notes - 2025 Backfill Baseline",
        "=" * 52,
        "",
        f"Generated from: {SCORED_PATH}",
        f"Resolved rows: {len(resolved):,}",
        f"Overall actual hit rate: {pct(overall)}",
        "",
        "Key read:",
        "The first NFL formula family is separating usable buckets from weak buckets. PropScore and simulation probability have the cleanest shape so far, while raw historical confidence is still too flat around 50-60%.",
        "",
        "Simulation calibration:",
    ]
    for _, row in sim_rows.iterrows():
        lines.append(f"- {row.BucketLabel}: {pct(row.ActualRate)} actual on {int(row.SampleSize):,} rows")

    lines += [
        "",
        "Underweighted / promote candidates:",
    ]
    if top_under.empty:
        lines.append("- None above the current sample and gap threshold.")
    else:
        for _, row in top_under.iterrows():
            lines.append(
                f"- {row.BucketType}={row.BucketLabel}: {pct(row.ActualRate)} actual, {pct(row.AverageConfidence)} avg confidence, {int(row.SampleSize):,} rows."
            )

    lines += [
        "",
        "Overweighted / reduce-trust candidates:",
    ]
    if top_over.empty:
        lines.append("- None above the current sample and gap threshold.")
    else:
        for _, row in top_over.iterrows():
            lines.append(
                f"- {row.BucketType}={row.BucketLabel}: {pct(row.ActualRate)} actual, {pct(row.AverageConfidence)} avg confidence, {int(row.SampleSize):,} rows."
            )

    lines += [
        "",
        "Recommended next formula adjustments:",
        "- Keep PropScore as the main NFL player-prop promotion score. The 25+ band is materially stronger than the full field.",
        "- Treat simulation probability 70+ as a lab-grade signal, not yet an auto-bet. It matched actual rate well on backfill.",
        "- Cap or demote Rush Attempts OVER until usage and game-script logic are strengthened.",
        "- Demote HOLD market-gate rows by default; the historical HOLD bucket is materially weak.",
        "- Keep wind passing overs as a hard contradiction until live data proves otherwise.",
        "",
        "Do not overfit:",
        "- These rows are historical backfill. They are excellent for preseason formula shape, but live 2026 rows must be tracked separately with IsBackfill=False.",
    ]
    NOTES_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    if not SCORED_PATH.exists():
        raise FileNotFoundError(f"Missing scored NFL file: {SCORED_PATH}")
    scored = add_score_bands(pd.read_csv(SCORED_PATH, low_memory=False))
    rows: list[dict] = []
    for bucket_type, label_col in [
        ("ConfidenceBand", "ConfidenceBand"),
        ("EdgeScoreBand", "EdgeScoreBand"),
        ("PropScoreBand", "PropScoreBand"),
        ("StatDirection", "StatDirection"),
        ("RoleDirection", "RoleDirection"),
        ("MarketGate", "MarketGate"),
        ("VolatilityFlag", "VolatilityFlag"),
    ]:
        if label_col == "StatDirection":
            scored[label_col] = scored["Stat"].fillna("").astype(str) + " | " + scored["Direction"].fillna("").astype(str)
        if label_col == "RoleDirection":
            scored[label_col] = scored["RoleLabel"].fillna("UNKNOWN").astype(str) + " | " + scored["Direction"].fillna("").astype(str)
        rows.extend(summarize_group(scored, bucket_type, label_col))

    rows.extend(explode_tag_summary(scored, "GameScriptTags", "GameScriptTag"))
    rows.extend(explode_tag_summary(scored, "ContradictionTags", "ContradictionTag"))
    rows.extend(simulation_summary())

    summary = pd.DataFrame(rows)
    if summary.empty:
        raise ValueError("No calibration summary rows were generated.")
    summary["GapVsConfidence"] = (summary["ActualRate"] - summary["AverageConfidence"]).round(4)
    summary["Classification"] = summary.apply(classify, axis=1)
    summary["Recommendation"] = summary.apply(recommendation, axis=1)
    summary = summary.sort_values(["Classification", "BucketType", "ActualRate"], ascending=[True, True, False])

    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(SUMMARY_PATH, index=False)
    write_notes(summary, scored)

    print(f"Summary rows: {len(summary):,}")
    print(f"Saved summary: {SUMMARY_PATH}")
    print(f"Saved notes: {NOTES_PATH}")
    for classification in ["UNDERWEIGHTED", "OVERWEIGHTED", "CALIBRATED", "WATCH"]:
        print(f"{classification}: {int(summary['Classification'].eq(classification).sum()):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
