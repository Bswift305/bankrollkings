from __future__ import annotations

from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
TRACKING_DIR = BASE_DIR / "data" / "tracking"
SPORTS = ["NBA", "WNBA", "MLB", "NFL"]
PLAYER_OUTPUT = TRACKING_DIR / "CrossSport_Player_Reliability_Summary.csv"
PROMOTION_OUTPUT = TRACKING_DIR / "Missed_Winner_Promotion_Candidates.csv"
NOTES_OUTPUT = TRACKING_DIR / "Promotion_Signal_Notes.txt"


def read_results(sport: str) -> pd.DataFrame:
    path = TRACKING_DIR / f"{sport}_AllPropResults.csv"
    if sport == "NFL" and (TRACKING_DIR / "NFL_AllPropResults_Scored.csv").exists():
        path = TRACKING_DIR / "NFL_AllPropResults_Scored.csv"
    if not path.exists() or path.stat().st_size <= 2:
        return pd.DataFrame()
    df = pd.read_csv(path, low_memory=False)
    df["Sport"] = sport
    return df


def reliability_label(resolved_count: int, hit_rate: float) -> str:
    if resolved_count < 3:
        return "TOO_SMALL"
    if resolved_count < 10:
        return "SMALL_SAMPLE"
    if resolved_count >= 20 and hit_rate >= 0.65:
        return "ANCHOR"
    if resolved_count >= 10 and hit_rate >= 0.60:
        return "WATCH"
    if resolved_count >= 10 and hit_rate < 0.52:
        return "AVOID"
    return "DEVELOPING"


def load_all_results() -> pd.DataFrame:
    frames = [read_results(sport) for sport in SPORTS]
    frames = [df for df in frames if not df.empty]
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined["OutcomeState"] = combined.get("OutcomeState", "").fillna("").astype(str)
    combined["ConfidenceNum"] = pd.to_numeric(combined.get("Confidence"), errors="coerce")
    combined["ResultDateParsed"] = pd.to_datetime(
        combined.get("ResultDate", combined.get("SnapshotDate")), errors="coerce"
    )
    combined["BucketKey"] = (
        combined.get("Sport", "").fillna("").astype(str)
        + "|"
        + combined.get("Stat", "").fillna("").astype(str).str.upper()
        + "|"
        + combined.get("Direction", "").fillna("").astype(str).str.upper()
    )
    return combined


def build_player_reliability(df: pd.DataFrame) -> pd.DataFrame:
    resolved = df[df["OutcomeState"].isin(["Hit", "Miss"])].copy()
    if resolved.empty:
        return pd.DataFrame()
    grouped = resolved.groupby(["Sport", "Player", "Stat", "Direction"], dropna=False)
    rows = []
    for (sport, player, stat, direction), group in grouped:
        count = int(len(group))
        if count < 3:
            continue
        hits = int(group["OutcomeState"].eq("Hit").sum())
        hit_rate = hits / count if count else 0.0
        rows.append(
            {
                "Sport": sport,
                "Player": player,
                "Stat": str(stat).upper(),
                "Direction": str(direction).upper(),
                "Resolved": count,
                "Hits": hits,
                "Misses": count - hits,
                "HitRate": round(hit_rate, 4),
                "AvgConfidence": round(float(group["ConfidenceNum"].mean()), 1) if group["ConfidenceNum"].notna().any() else None,
                "Reliability": reliability_label(count, hit_rate),
                "LastResultDate": group["ResultDateParsed"].max(),
            }
        )
    output = pd.DataFrame(rows)
    if not output.empty:
        output = output.sort_values(["Reliability", "HitRate", "Resolved"], ascending=[True, False, False])
    return output


def build_missed_winner_candidates(df: pd.DataFrame, profiles: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    resolved_hits = df[df["OutcomeState"].eq("Hit")].copy()
    method = resolved_hits.get("Method", "").fillna("").astype(str).str.upper()
    missed = resolved_hits[
        method.str.contains("AVAILABLE", na=False)
        | method.str.contains("ARCHIVE", na=False)
        | resolved_hits.get("BetTier", pd.Series(index=resolved_hits.index, dtype=str)).fillna("").eq("")
    ].copy()
    missed = missed[missed["ConfidenceNum"].fillna(0) >= 60].copy()
    if missed.empty:
        return pd.DataFrame()

    bucket_counts = missed.groupby("BucketKey").size().to_dict()
    profile_lookup = {}
    if not profiles.empty:
        for _, row in profiles.iterrows():
            key = (
                str(row.get("Sport")),
                str(row.get("Player")),
                str(row.get("Stat")).upper(),
                str(row.get("Direction")).upper(),
            )
            profile_lookup[key] = row.to_dict()

    rows = []
    for _, row in missed.iterrows():
        key = (
            str(row.get("Sport")),
            str(row.get("Player")),
            str(row.get("Stat")).upper(),
            str(row.get("Direction")).upper(),
        )
        profile = profile_lookup.get(key, {})
        reliability = profile.get("Reliability", "UNKNOWN")
        bucket_count = int(bucket_counts.get(row.get("BucketKey"), 0))
        confidence = float(row.get("ConfidenceNum") or 0)
        grade = 0
        grade += 30 if confidence >= 80 else 20 if confidence >= 70 else 10
        grade += 25 if reliability == "ANCHOR" else 15 if reliability == "WATCH" else 5 if reliability == "SMALL_SAMPLE" else 0
        grade += min(bucket_count * 5, 20)
        if str(row.get("MarketGate") or "").upper() == "CLEAR":
            grade += 10
        if str(row.get("VolatilityFlag") or "").upper() == "STABLE":
            grade += 5

        if grade >= 80 and reliability in {"ANCHOR", "WATCH"}:
            signal = "PROMOTE_HARD"
        elif grade >= 65 and reliability in {"ANCHOR", "WATCH", "SMALL_SAMPLE"}:
            signal = "PROMOTE"
        elif grade >= 50:
            signal = "SURFACE"
        else:
            signal = "REVIEW"

        rows.append(
            {
                "Sport": row.get("Sport"),
                "Player": row.get("Player"),
                "Stat": str(row.get("Stat") or "").upper(),
                "Direction": str(row.get("Direction") or "").upper(),
                "Line": row.get("Line"),
                "Confidence": round(confidence, 1),
                "ResultDate": row.get("ResultDate"),
                "Matchup": row.get("Matchup"),
                "MarketPrice": row.get("MarketPrice"),
                "BucketKey": row.get("BucketKey"),
                "BucketMissedWinnerCount": bucket_count,
                "PlayerReliability": reliability,
                "PlayerResolved": profile.get("Resolved"),
                "PlayerHitRate": profile.get("HitRate"),
                "MissedWinnerGrade": int(min(100, grade)),
                "PromotionSignal": signal,
            }
        )
    output = pd.DataFrame(rows)
    return output.sort_values(["PromotionSignal", "MissedWinnerGrade", "Confidence"], ascending=[True, False, False])


def write_notes(profiles: pd.DataFrame, promotions: pd.DataFrame) -> None:
    anchors = profiles[profiles["Reliability"].eq("ANCHOR")] if not profiles.empty else pd.DataFrame()
    watches = profiles[profiles["Reliability"].eq("WATCH")] if not profiles.empty else pd.DataFrame()
    promote_hard = promotions[promotions["PromotionSignal"].eq("PROMOTE_HARD")] if not promotions.empty else pd.DataFrame()
    lines = [
        "Promotion Signal Notes",
        "=" * 30,
        "",
        f"Player ANCHOR profiles: {len(anchors):,}",
        f"Player WATCH profiles: {len(watches):,}",
        f"PROMOTE_HARD missed winners: {len(promote_hard):,}",
        "",
        "Interpretation:",
        "- Player reliability answers whether this player has actually delivered in this stat/direction bucket.",
        "- Missed winners answer where the formula found a winner that did not become a primary surface.",
        "- When both agree, the next live board should promote that bucket harder, after contradiction QC.",
        "",
        "Top promote candidates:",
    ]
    if promote_hard.empty:
        lines.append("- None yet.")
    else:
        for _, row in promote_hard.head(12).iterrows():
            hit_rate = row.get("PlayerHitRate")
            hit_label = f"{float(hit_rate) * 100:.1f}%" if pd.notna(hit_rate) else "-"
            lines.append(
                f"- {row.Sport} {row.Player} {row.Stat} {row.Direction}: grade {row.MissedWinnerGrade}, "
                f"profile {row.PlayerReliability} ({hit_label}), bucket count {row.BucketMissedWinnerCount}."
            )
    NOTES_OUTPUT.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    df = load_all_results()
    profiles = build_player_reliability(df)
    promotions = build_missed_winner_candidates(df, profiles)
    PLAYER_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    profiles.to_csv(PLAYER_OUTPUT, index=False)
    promotions.to_csv(PROMOTION_OUTPUT, index=False)
    write_notes(profiles, promotions)
    print(f"Saved player reliability: {PLAYER_OUTPUT} ({len(profiles):,} rows)")
    print(f"Saved promotion candidates: {PROMOTION_OUTPUT} ({len(promotions):,} rows)")
    print(f"Saved notes: {NOTES_OUTPUT}")
    if not promotions.empty:
        print(promotions[["Sport", "Player", "Stat", "Direction", "MissedWinnerGrade", "PromotionSignal"]].head(10).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
