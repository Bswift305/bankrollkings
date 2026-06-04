from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
TRACKING_DIR = BASE_DIR / "data" / "tracking"
SPORTS = ["NBA", "WNBA", "MLB", "NFL", "NCAAF"]
OUTPUT_PATH = TRACKING_DIR / "Live_Drift_Alerts.csv"
NOTES_PATH = TRACKING_DIR / "Live_Drift_Notes.txt"


def _read_results(sport: str) -> pd.DataFrame:
    path = TRACKING_DIR / f"{sport}_AllPropResults.csv"
    if sport == "NFL" and (TRACKING_DIR / "NFL_AllPropResults_Scored.csv").exists():
        path = TRACKING_DIR / "NFL_AllPropResults_Scored.csv"
    if not path.exists() or path.stat().st_size <= 2:
        return pd.DataFrame()
    try:
        df = pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()
    df["Sport"] = sport
    return df


def _load_all() -> pd.DataFrame:
    frames = [_read_results(sport) for sport in SPORTS]
    frames = [df for df in frames if not df.empty]
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True, sort=False)
    for col in ["OutcomeState", "Sport", "Stat", "Direction", "Method", "BetTier", "ResultDate", "SnapshotDate", "IsBackfill"]:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str)
    df["ResultDateParsed"] = pd.to_datetime(
        df["ResultDate"].where(df["ResultDate"].str.strip().ne(""), df["SnapshotDate"]),
        errors="coerce",
    )
    df["HitBinary"] = df["OutcomeState"].eq("Hit").astype(int)
    df["IsBackfillBool"] = df["IsBackfill"].str.lower().isin(["true", "1", "yes"])
    for col in ["CloseLine", "BetLine", "CurrentLine", "Line"]:
        if col not in df.columns:
            df[col] = ""
        df[col + "Num"] = pd.to_numeric(df[col], errors="coerce")
    bet_line = df["BetLineNum"].where(df["BetLineNum"].notna(), df["CurrentLineNum"])
    bet_line = bet_line.where(bet_line.notna(), df["LineNum"])
    close_line = df["CloseLineNum"]
    direction = df["Direction"].str.upper()
    df["ComputedClvLine"] = pd.NA
    over_mask = direction.eq("OVER") & close_line.notna() & bet_line.notna()
    under_mask = direction.eq("UNDER") & close_line.notna() & bet_line.notna()
    df.loc[over_mask, "ComputedClvLine"] = close_line[over_mask] - bet_line[over_mask]
    df.loc[under_mask, "ComputedClvLine"] = bet_line[under_mask] - close_line[under_mask]
    df["ComputedClvLine"] = pd.to_numeric(df["ComputedClvLine"], errors="coerce")
    df["ClvBucket"] = "NO_CLV"
    df.loc[df["ComputedClvLine"].ge(0.1), "ClvBucket"] = "POSITIVE_CLV"
    df.loc[df["ComputedClvLine"].le(-0.1), "ClvBucket"] = "NEGATIVE_CLV"
    df.loc[df["ComputedClvLine"].abs().lt(0.1), "ClvBucket"] = "FLAT_CLV"
    df["Bucket"] = (
        df["Sport"].str.upper()
        + "|"
        + df["Stat"].str.upper()
        + "|"
        + df["Direction"].str.upper()
    )
    return df[df["OutcomeState"].isin(["Hit", "Miss"])].copy()


def _alert_label(delta: float, comparison_rate: float, comparison_n: int) -> str:
    if comparison_n < 20:
        return "WATCH_THIN_SAMPLE"
    if delta <= -0.10:
        return "DRIFT_DOWN"
    if delta >= 0.10:
        return "DRIFT_UP"
    if comparison_rate < 0.50:
        return "UNDERPERFORMING"
    return "STABLE"


def _add_row(rows: list[dict], scope: str, sport: str, bucket: str, baseline: pd.DataFrame, comparison: pd.DataFrame) -> None:
    if baseline.empty or comparison.empty:
        return
    baseline_n = int(len(baseline))
    comparison_n = int(len(comparison))
    if scope == "LAST_30_VS_ALL" and baseline_n == comparison_n:
        return
    if baseline_n < 30 or comparison_n < 10:
        return
    baseline_rate = float(baseline["HitBinary"].mean())
    comparison_rate = float(comparison["HitBinary"].mean())
    delta = comparison_rate - baseline_rate
    rows.append({
        "Scope": scope,
        "Sport": sport,
        "Bucket": bucket,
        "BaselineSample": baseline_n,
        "ComparisonSample": comparison_n,
        "BaselineHitRate": round(baseline_rate, 4),
        "ComparisonHitRate": round(comparison_rate, 4),
        "Delta": round(delta, 4),
        "Alert": _alert_label(delta, comparison_rate, comparison_n),
        "CheckedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


def build_drift_alerts() -> pd.DataFrame:
    df = _load_all()
    if df.empty:
        return pd.DataFrame(columns=[
            "Scope", "Sport", "Bucket", "BaselineSample", "ComparisonSample",
            "BaselineHitRate", "ComparisonHitRate", "Delta", "Alert", "CheckedAt",
        ])

    rows: list[dict] = []
    cutoff = datetime.now() - timedelta(days=30)
    recent = df[df["ResultDateParsed"].ge(cutoff)].copy()

    for (sport, bucket), group in df.groupby(["Sport", "Bucket"], dropna=False):
        sport = str(sport).upper()
        bucket = str(bucket)
        recent_group = recent[recent["Bucket"].eq(bucket) & recent["Sport"].eq(sport)]
        _add_row(rows, "LAST_30_VS_ALL", sport, bucket, group, recent_group)

        backfill = group[group["IsBackfillBool"]].copy()
        live = group[~group["IsBackfillBool"]].copy()
        _add_row(rows, "LIVE_VS_BACKFILL", sport, bucket, backfill, live)

        method = group["Method"].str.upper()
        featured = group[method.str.contains("FEATURED|FLOOR PLAY|MARKET EDGE|TREND", na=False)].copy()
        unplayed = group.drop(featured.index, errors="ignore")
        _add_row(rows, "FEATURED_VS_UNPLAYED", sport, bucket, unplayed, featured)

        clv_rows = group[group["ClvBucket"].ne("NO_CLV")].copy()
        positive_clv = clv_rows[clv_rows["ClvBucket"].eq("POSITIVE_CLV")].copy()
        nonpositive_clv = clv_rows[~clv_rows["ClvBucket"].eq("POSITIVE_CLV")].copy()
        _add_row(rows, "POSITIVE_CLV_VS_NONPOSITIVE", sport, bucket, nonpositive_clv, positive_clv)

    output = pd.DataFrame(rows)
    if not output.empty:
        alert_order = {
            "DRIFT_DOWN": 0,
            "UNDERPERFORMING": 1,
            "DRIFT_UP": 2,
            "WATCH_THIN_SAMPLE": 3,
            "STABLE": 4,
        }
        output["_AlertOrder"] = output["Alert"].map(alert_order).fillna(9)
        output = output.sort_values(["_AlertOrder", "Delta", "ComparisonSample"], ascending=[True, True, False])
        output = output.drop(columns=["_AlertOrder"])
    return output


def write_notes(alerts: pd.DataFrame) -> None:
    lines = [
        "Live Drift Notes",
        "=" * 24,
        "",
        "Purpose:",
        "- Compare recent/live/featured performance against historical baselines.",
        "- Catch buckets that were strong in backfill but are weakening live.",
        "- Catch buckets where featured performance is worse than unplayed performance.",
        "",
    ]
    if alerts.empty:
        lines.append("No drift alerts were generated.")
    else:
        for label in ["DRIFT_DOWN", "UNDERPERFORMING", "DRIFT_UP"]:
            subset = alerts[alerts["Alert"].eq(label)]
            lines.append(f"{label}: {len(subset):,}")
            for _, row in subset.head(8).iterrows():
                lines.append(
                    f"- {row.Scope} {row.Bucket}: "
                    f"{float(row.ComparisonHitRate) * 100:.1f}% vs "
                    f"{float(row.BaselineHitRate) * 100:.1f}% baseline "
                    f"({int(row.ComparisonSample)} comparison rows)."
                )
            lines.append("")
    NOTES_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    alerts = build_drift_alerts()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    alerts.to_csv(OUTPUT_PATH, index=False)
    write_notes(alerts)
    print("=" * 60)
    print("BANKROLL KINGS - LIVE DRIFT ALERTS")
    print("=" * 60)
    print(f"Rows written: {len(alerts):,}")
    print(f"Output: {OUTPUT_PATH}")
    print(f"Notes: {NOTES_PATH}")
    if not alerts.empty:
        print(alerts.head(12).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
