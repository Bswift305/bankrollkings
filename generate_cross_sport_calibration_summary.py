from __future__ import annotations

from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
TRACKING_DIR = BASE_DIR / "data" / "tracking"
SPORTS = ["NBA", "WNBA", "MLB", "NFL", "NCAAF"]
OUTPUT_PATH = TRACKING_DIR / "CrossSport_Calibration_Summary.csv"
NOTES_PATH = TRACKING_DIR / "CrossSport_Calibration_Notes.txt"


def pct(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{value * 100:.1f}%"


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size <= 2:
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def confidence_band(rate: float | None) -> str:
    if rate is None or pd.isna(rate):
        return "NO_DATA"
    if rate >= 0.60:
        return "STRONG"
    if rate >= 0.54:
        return "WATCH"
    if rate <= 0.47:
        return "WEAK"
    return "CALIBRATED"


def summarize_sport(sport: str) -> dict:
    results_path = TRACKING_DIR / f"{sport}_AllPropResults.csv"
    if sport == "NFL" and (TRACKING_DIR / "NFL_AllPropResults_Scored.csv").exists():
        results_path = TRACKING_DIR / "NFL_AllPropResults_Scored.csv"
    if sport == "MLB" and (TRACKING_DIR / "MLB_AllPropResults_Scored.csv").exists():
        results_path = TRACKING_DIR / "MLB_AllPropResults_Scored.csv"
    if sport == "NCAAF" and (TRACKING_DIR / "NCAAF_GameLineResults_Scored.csv").exists():
        results_path = TRACKING_DIR / "NCAAF_GameLineResults_Scored.csv"
    report_path = TRACKING_DIR / f"{sport}_Calibration_Report.csv"

    results = read_csv(results_path)
    report = read_csv(report_path)
    resolved = results[results.get("OutcomeState", pd.Series(dtype=str)).isin(["Hit", "Miss"])].copy() if not results.empty else pd.DataFrame()
    pending = results[results.get("OutcomeState", pd.Series(dtype=str)).eq("Pending")].copy() if not results.empty else pd.DataFrame()
    hit_rate = float(resolved["OutcomeState"].eq("Hit").mean()) if not resolved.empty else None

    classifications = report.get("Classification", pd.Series(dtype=str)).fillna("").astype(str).str.upper() if not report.empty else pd.Series(dtype=str)
    strong_count = int(classifications.eq("STRONG").sum() + classifications.eq("UNDERWEIGHTED").sum())
    lying_count = int(classifications.eq("LYING").sum() + classifications.eq("OVERWEIGHTED").sum())
    watch_count = int(classifications.eq("WATCH").sum())

    high_conf_rate = None
    high_conf_rows = 0
    if not resolved.empty and "Confidence" in resolved.columns:
        conf = pd.to_numeric(resolved["Confidence"], errors="coerce")
        high_conf = resolved[conf >= 70]
        high_conf_rows = int(len(high_conf))
        if not high_conf.empty:
            high_conf_rate = float(high_conf["OutcomeState"].eq("Hit").mean())

    return {
        "Sport": sport,
        "ResultsFile": results_path.name,
        "ReportFile": report_path.name if report_path.exists() else "",
        "TotalRows": int(len(results)),
        "ResolvedRows": int(len(resolved)),
        "PendingRows": int(len(pending)),
        "OverallHitRate": round(hit_rate, 4) if hit_rate is not None else None,
        "OverallStatus": confidence_band(hit_rate),
        "HighConfidenceHitRate": round(high_conf_rate, 4) if high_conf_rate is not None else None,
        "HighConfidenceRows": high_conf_rows,
        "HighConfidenceStatus": confidence_band(high_conf_rate),
        "CalibrationBuckets": int(len(report)),
        "StrongBuckets": strong_count,
        "WeakBuckets": lying_count,
        "WatchBuckets": watch_count,
        "DataStatus": "LIVE" if len(results) else "NO_DATA",
    }


def write_notes(summary: pd.DataFrame) -> None:
    live = summary[summary["DataStatus"].eq("LIVE")].copy()
    lines = [
        "Cross-Sport Calibration Notes",
        "=" * 35,
        "",
        "Purpose:",
        "Use one calibration workflow across sports while keeping each sport's formula weights separate.",
        "",
        "Sport reads:",
    ]
    if live.empty:
        lines.append("- No live calibration data found.")
    else:
        for _, row in live.iterrows():
            lines.append(
                f"- {row.Sport}: {pct(row.OverallHitRate)} overall on {int(row.ResolvedRows):,} resolved rows; "
                f"{pct(row.HighConfidenceHitRate)} on {int(row.HighConfidenceRows):,} 70+ confidence rows; "
                f"{int(row.StrongBuckets)} strong buckets, {int(row.WeakBuckets)} weak buckets, {int(row.WatchBuckets)} watch buckets."
            )

    lines += [
        "",
        "Operating rule:",
        "- Do not share formula weights across sports.",
        "- Do share the calibration questions: did confidence match outcomes, did higher bands outperform lower bands, did market gates add value, and did missed winners reveal promotion buckets.",
        "",
        "Next build:",
        "- Add sport-specific Formula Lab pages for NBA, WNBA, MLB, NFL.",
        "- Add one shared Calibration Lab view that compares sport health and links into each sport-specific lab.",
    ]
    NOTES_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    rows = [summarize_sport(sport) for sport in SPORTS]
    summary = pd.DataFrame(rows)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(OUTPUT_PATH, index=False)
    write_notes(summary)
    print(f"Saved summary: {OUTPUT_PATH}")
    print(f"Saved notes: {NOTES_PATH}")
    for _, row in summary.iterrows():
        print(
            f"{row.Sport}: {int(row.ResolvedRows):,} resolved | {pct(row.OverallHitRate)} overall | "
            f"{pct(row.HighConfidenceHitRate)} 70+ ({int(row.HighConfidenceRows):,}) | {row.DataStatus}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
