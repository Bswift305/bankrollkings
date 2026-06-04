from __future__ import annotations

from pathlib import Path

import pandas as pd

from services.statcast_loader import build_statcast_prop_signal


BASE_DIR = Path(__file__).resolve().parent
TRACKING_DIR = BASE_DIR / "data" / "tracking"
CONTEXT_PATH = BASE_DIR / "data" / "context" / "MLB_GameContext.csv"
ODDS_PATH = BASE_DIR / "data" / "odds" / "MLB_Odds.csv"
INPUT_PATH = TRACKING_DIR / "MLB_AllPropResults.csv"
OUTPUT_PATH = TRACKING_DIR / "MLB_AllPropResults_Scored.csv"
SUMMARY_PATH = TRACKING_DIR / "MLB_Formula_Calibration_Summary.csv"
NOTES_PATH = TRACKING_DIR / "Calibration_Notes_MLB_2026.txt"

PITCHER_STATS = {
    "PITCHER KS",
    "PITCHER HITS ALLOWED",
    "PITCHER EARNED RUNS",
    "PITCHER OUTS",
    "PITCHER WIN",
}
HITTER_STATS = {
    "HITS",
    "TOTAL BASES",
    "HOME RUNS",
    "RBIS",
    "RUNS",
    "SINGLES",
    "DOUBLES",
    "TRIPLES",
    "STOLEN BASES",
    "HITS + RUNS + RBIS",
    "BATTER WALKS",
    "BATTER STRIKEOUTS",
}


def to_float(value, default: float = 0.0) -> float:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return default
    return float(parsed)


def normalize_game(value) -> str:
    text = str(value or "").replace("@", " @ ")
    return " ".join(text.split()).upper()


def context_lookup() -> dict:
    lookup: dict[str, dict] = {}
    if CONTEXT_PATH.exists() and CONTEXT_PATH.stat().st_size > 2:
        context = pd.read_csv(CONTEXT_PATH, low_memory=False)
        for _, row in context.iterrows():
            away = str(row.get("Away") or "").strip()
            home = str(row.get("Home") or "").strip()
            if not away or not home:
                continue
            key = normalize_game(f"{away} @ {home}")
            lookup[key] = {
                "Ballpark": row.get("Ballpark"),
                "ParkHRFactor": to_float(row.get("ParkHRFactor"), 1.0),
                "Temperature": to_float(row.get("Temperature"), float("nan")),
                "WindMph": to_float(row.get("WindMph"), float("nan")),
                "WindDirection": str(row.get("WindDirection") or "").upper(),
                "UmpireZone": str(row.get("UmpireZone") or "").upper(),
            }

    if ODDS_PATH.exists() and ODDS_PATH.stat().st_size > 2:
        odds = pd.read_csv(ODDS_PATH, low_memory=False)
        for _, row in odds.iterrows():
            away = str(row.get("AwayFull") or row.get("Away") or "").strip()
            home = str(row.get("HomeFull") or row.get("Home") or "").strip()
            if not away or not home:
                continue
            key = normalize_game(f"{away} @ {home}")
            payload = lookup.setdefault(key, {})
            totals = odds[
                (odds.get("AwayFull", odds.get("Away")).fillna("").astype(str).str.upper() == away.upper())
                & (odds.get("HomeFull", odds.get("Home")).fillna("").astype(str).str.upper() == home.upper())
            ]
            payload["GameTotal"] = round(float(pd.to_numeric(totals.get("Total"), errors="coerce").dropna().mean()), 1) if "Total" in totals else None
            payload["BookCount"] = int(totals["Book"].nunique()) if "Book" in totals.columns else int(len(totals))
    return lookup


def environment_score(stat: str, direction: str, ctx: dict) -> tuple[float, str]:
    score = 0.0
    tags = []
    total = ctx.get("GameTotal")
    park = ctx.get("ParkHRFactor")
    wind = ctx.get("WindMph")
    wind_dir = str(ctx.get("WindDirection") or "").upper()
    temp = ctx.get("Temperature")
    zone = str(ctx.get("UmpireZone") or "").upper()

    if total is not None and pd.notna(total):
        if total <= 7.5:
            tags.append("PITCHER_FRIENDLY_TOTAL")
            if direction == "UNDER" and stat in HITTER_STATS:
                score += 8
            if direction == "OVER" and stat in PITCHER_STATS:
                score += 5
        elif total >= 9:
            tags.append("HITTER_FRIENDLY_TOTAL")
            if direction == "OVER" and stat in HITTER_STATS:
                score += 7
            if direction == "UNDER" and stat in PITCHER_STATS:
                score += 4
    if park is not None and pd.notna(park) and park >= 1.08:
        tags.append("HR_PARK")
        if stat in {"HOME RUNS", "TOTAL BASES"} and direction == "OVER":
            score += 6
        if stat in {"HOME RUNS", "TOTAL BASES"} and direction == "UNDER":
            score -= 8
    elif park is not None and pd.notna(park) and park <= 0.92:
        tags.append("HR_SUPPRESSION_PARK")
        if stat in {"HOME RUNS", "TOTAL BASES"} and direction == "UNDER":
            score += 6
        if stat in {"HOME RUNS", "TOTAL BASES"} and direction == "OVER":
            score -= 8
    if pd.notna(wind) and wind >= 12:
        tags.append("WIND_ACTIVE")
        if "OUT" in wind_dir:
            tags.append("WIND_OUT")
            if stat in {"HOME RUNS", "TOTAL BASES"} and direction == "OVER":
                score += 6
            if stat in {"HOME RUNS", "TOTAL BASES"} and direction == "UNDER":
                score -= 8
        elif "IN" in wind_dir:
            tags.append("WIND_IN")
            if stat in {"HOME RUNS", "TOTAL BASES"} and direction == "UNDER":
                score += 6
            if stat in {"HOME RUNS", "TOTAL BASES"} and direction == "OVER":
                score -= 8
        elif wind >= 15:
            tags.append("WIND_DIRECTION_UNKNOWN")
            if stat in {"HOME RUNS", "TOTAL BASES"}:
                score -= 2
    if temp is not None and pd.notna(temp):
        if temp <= 50:
            tags.append("COLD_WEATHER")
            if stat in HITTER_STATS and direction == "UNDER":
                score += 3
            if stat in HITTER_STATS and direction == "OVER":
                score -= 4
        elif temp >= 85:
            tags.append("HOT_WEATHER")
            if stat in HITTER_STATS and direction == "OVER":
                score += 3
            if stat in HITTER_STATS and direction == "UNDER":
                score -= 3
    if zone == "WIDE":
        tags.append("WIDE_ZONE")
        if stat == "PITCHER KS" and direction == "OVER":
            score += 8
        if stat == "PITCHER KS" and direction == "UNDER":
            score -= 8
    elif zone == "TIGHT":
        tags.append("TIGHT_ZONE")
        if stat == "PITCHER KS" and direction == "UNDER":
            score += 8
        if stat == "PITCHER KS" and direction == "OVER":
            score -= 8
    return score, "|".join(tags)


def _statcast_signal_for_row(row: pd.Series, stat: str, direction: str, cache: dict[tuple[str, str, str], dict]) -> dict:
    key = (
        str(row.get("Player") or "").strip(),
        str(stat or "").strip().upper(),
        str(direction or "").strip().upper(),
    )
    if key not in cache:
        cache[key] = build_statcast_prop_signal(key[0], key[1], key[2])
    return cache[key]


def score_row(row: pd.Series, ctx_lookup: dict, statcast_cache: dict[tuple[str, str, str], dict]) -> dict:
    stat = str(row.get("Stat") or "").strip().upper()
    direction = str(row.get("Direction") or "").strip().upper()
    confidence = to_float(row.get("Confidence"), 50.0)
    book_count = to_float(row.get("BookCount"), 1.0)
    price = abs(to_float(row.get("MarketPrice"), 110.0))
    market_gate = str(row.get("MarketGate") or "").upper()
    volatility = str(row.get("VolatilityFlag") or "").upper()
    method = str(row.get("Method") or "").upper()

    ctx = ctx_lookup.get(normalize_game(row.get("Matchup")), {})
    env_score, env_tags = environment_score(stat, direction, ctx)
    role = "PITCHER" if stat in PITCHER_STATS else "HITTER" if stat in HITTER_STATS else "OTHER"

    market_score = 0.0
    if book_count >= 3:
        market_score += 8
    elif book_count == 2:
        market_score += 4
    else:
        market_score -= 7
    if market_gate == "CLEAR":
        market_score += 6
    elif market_gate == "HOLD":
        market_score -= 8
    if price >= 800 and direction == "UNDER":
        market_score += 4
    if price <= 120:
        market_score -= 2

    confidence_score = max(-15.0, min(25.0, (confidence - 55.0) * 0.7))
    volatility_penalty = 0.0
    if volatility and volatility != "STABLE":
        volatility_penalty += 6
    if "AVAILABLE" in method and book_count < 2:
        volatility_penalty += 5
    if ctx and to_float(ctx.get("WindMph"), 0.0) >= 15:
        volatility_penalty += 2

    hitter_score = None
    pitcher_score = None
    if role == "HITTER":
        hitter_score = round(confidence_score + market_score + env_score - volatility_penalty, 1)
    elif role == "PITCHER":
        pitcher_score = round(confidence_score + market_score + env_score - volatility_penalty, 1)
    overall = hitter_score if hitter_score is not None else pitcher_score if pitcher_score is not None else round(confidence_score + market_score - volatility_penalty, 1)
    statcast_signal = _statcast_signal_for_row(row, stat, direction, statcast_cache)
    statcast_modifier = to_float(statcast_signal.get("score_delta"), 0.0) if statcast_signal.get("available") else 0.0
    statcast_note = " - ".join(part for part in ["|".join(statcast_signal.get("tags") or []), str(statcast_signal.get("note") or "").strip()] if part)
    overall = round(overall + statcast_modifier, 1)
    if hitter_score is not None:
        hitter_score = round(hitter_score + statcast_modifier, 1)
    if pitcher_score is not None:
        pitcher_score = round(pitcher_score + statcast_modifier, 1)

    return {
        "MLBRole": role,
        "MLBMarketScore": round(market_score, 1),
        "MLBEnvironmentScore": round(env_score, 1),
        "MLBVolatilityPenalty": round(volatility_penalty, 1),
        "MLBHitterScore": hitter_score,
        "MLBPitcherScore": pitcher_score,
        "MLBStatcastModifier": round(statcast_modifier, 1),
        "MLBStatcastNote": statcast_note,
        "BK_MLB_ContextScore": round(overall, 1),
        "MLBEnvironmentTags": env_tags,
        "MLBModelVersion": "MLB_ContextScore_v1",
    }


def reliability_summary(scored: pd.DataFrame) -> pd.DataFrame:
    resolved = scored[scored["OutcomeState"].isin(["Hit", "Miss"])].copy()
    rows = []
    if resolved.empty:
        return pd.DataFrame()
    resolved["ContextScoreBand"] = pd.cut(
        pd.to_numeric(resolved["BK_MLB_ContextScore"], errors="coerce"),
        bins=[-999, 0, 10, 20, 999],
        labels=["<0", "0-10", "10-20", "20+"],
    ).astype(str)
    for bucket_type, column in [
        ("ContextScoreBand", "ContextScoreBand"),
        ("Role", "MLBRole"),
        ("StatDirection", "StatDirection"),
        ("EnvironmentTags", "MLBEnvironmentTags"),
        ("MarketGate", "MarketGate"),
    ]:
        if column == "StatDirection":
            resolved[column] = resolved["Stat"].fillna("").astype(str).str.upper() + " | " + resolved["Direction"].fillna("").astype(str).str.upper()
        if column == "MLBEnvironmentTags":
            exploded = []
            for _, row in resolved.iterrows():
                tags = [tag for tag in str(row.get(column) or "").split("|") if tag]
                for tag in tags or ["NO_CONTEXT_TAG"]:
                    item = row.copy()
                    item[column] = tag
                    exploded.append(item)
            frame = pd.DataFrame(exploded)
        else:
            frame = resolved
        for label, group in frame.groupby(column, dropna=False):
            if len(group) < 25:
                continue
            actual = float(group["OutcomeState"].eq("Hit").mean())
            avg_conf = float(pd.to_numeric(group["Confidence"], errors="coerce").mean()) / 100.0
            if len(group) >= 100 and actual >= 0.60 and actual - avg_conf >= 0.03:
                cls = "UNDERWEIGHTED"
            elif len(group) >= 100 and actual <= 0.47 and actual - avg_conf <= -0.05:
                cls = "OVERWEIGHTED"
            elif abs(actual - avg_conf) <= 0.05:
                cls = "CALIBRATED"
            else:
                cls = "WATCH"
            rows.append(
                {
                    "BucketType": bucket_type,
                    "BucketLabel": str(label),
                    "SampleSize": int(len(group)),
                    "ActualRate": round(actual, 4),
                    "AverageConfidence": round(avg_conf, 4),
                    "AverageContextScore": round(float(pd.to_numeric(group["BK_MLB_ContextScore"], errors="coerce").mean()), 2),
                    "Classification": cls,
                }
            )
    return pd.DataFrame(rows).sort_values(["Classification", "ActualRate"], ascending=[True, False])


def write_notes(summary: pd.DataFrame, scored: pd.DataFrame) -> None:
    resolved = scored[scored["OutcomeState"].isin(["Hit", "Miss"])].copy()
    overall = float(resolved["OutcomeState"].eq("Hit").mean()) if not resolved.empty else None
    promote = summary[summary["Classification"].eq("UNDERWEIGHTED")].sort_values(["ActualRate", "SampleSize"], ascending=[False, False]).head(10)
    reduce = summary[summary["Classification"].eq("OVERWEIGHTED")].sort_values(["ActualRate", "SampleSize"], ascending=[True, False]).head(10)
    lines = [
        "MLB Calibration Notes - ContextScore v1",
        "=" * 44,
        "",
        f"Resolved rows: {len(resolved):,}",
        f"Overall hit rate: {overall * 100:.1f}%" if overall is not None else "Overall hit rate: -",
        "",
        "Promote candidates:",
    ]
    if promote.empty:
        lines.append("- None above current thresholds.")
    else:
        for _, row in promote.iterrows():
            lines.append(f"- {row.BucketType}={row.BucketLabel}: {row.ActualRate * 100:.1f}% on {int(row.SampleSize):,} rows.")
    lines.append("")
    lines.append("Reduce-trust candidates:")
    if reduce.empty:
        lines.append("- None above current thresholds.")
    else:
        for _, row in reduce.iterrows():
            lines.append(f"- {row.BucketType}={row.BucketLabel}: {row.ActualRate * 100:.1f}% on {int(row.SampleSize):,} rows.")
    lines += [
        "",
        "Next MLB build:",
        "- Replace static ballpark context with live weather and umpire assignments.",
        "- Add batter-vs-pitcher and platoon split inputs.",
        "- Split hitter unders from hitter overs more aggressively, especially Home Runs and Total Bases.",
    ]
    NOTES_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    if not INPUT_PATH.exists():
        raise FileNotFoundError(f"Missing MLB results: {INPUT_PATH}")
    df = pd.read_csv(INPUT_PATH, low_memory=False)
    ctx = context_lookup()
    scored = df.copy()
    statcast_cache: dict[tuple[str, str, str], dict] = {}
    additions = [score_row(row, ctx, statcast_cache) for _, row in scored.iterrows()]
    add_df = pd.DataFrame(additions)
    for column in add_df.columns:
        scored[column] = add_df[column].values
    scored.to_csv(OUTPUT_PATH, index=False)
    summary = reliability_summary(scored)
    summary.to_csv(SUMMARY_PATH, index=False)
    write_notes(summary, scored)
    resolved = scored[scored["OutcomeState"].isin(["Hit", "Miss"])].copy()
    print(f"Rows scored: {len(scored):,}")
    print(f"Resolved: {len(resolved):,}")
    print(f"Saved scored: {OUTPUT_PATH}")
    print(f"Saved summary: {SUMMARY_PATH}")
    print(f"Saved notes: {NOTES_PATH}")
    if not summary.empty:
        print(summary.head(12).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
