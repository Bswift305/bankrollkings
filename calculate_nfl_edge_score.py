from __future__ import annotations

from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
INPUT_PATH = BASE_DIR / "data" / "tracking" / "NFL_AllPropResults.csv"
OUTPUT_PATH = BASE_DIR / "data" / "tracking" / "NFL_AllPropResults_Scored.csv"
MODEL_VERSION = "NFL_EdgeScore_v1"


def to_float(value, default: float = 0.0) -> float:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return default
    return float(parsed)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def tags_from(value) -> set[str]:
    text = str(value or "").upper()
    return {part.strip() for part in text.split("|") if part.strip()}


def calculate_projection_edge(row: pd.Series) -> float:
    confidence = to_float(row.get("Confidence"), 50.0)
    return clamp((confidence - 50.0) * 0.8, -20.0, 20.0)


def calculate_market_edge(row: pd.Series) -> float:
    market_gate = str(row.get("MarketGate") or "CLEAR").upper()
    market_depth = str(row.get("MarketDepthBucket") or "").upper()
    line_move = to_float(row.get("LineMove"), 0.0)
    clv_line = pd.to_numeric(pd.Series([row.get("ClvLine")]), errors="coerce").iloc[0]

    score = 0.0
    if market_gate == "CLEAR":
        score += 4.0
    elif market_gate == "HOLD":
        score -= 12.0

    if "MULTI" in market_depth or "DEEP" in market_depth:
        score += 2.0
    elif "THIN" in market_depth:
        score -= 4.0

    direction = str(row.get("Direction") or "").upper()
    if direction == "OVER" and line_move > 0:
        score += 2.0
    elif direction == "OVER" and line_move < 0:
        score -= 2.0
    elif direction == "UNDER" and line_move < 0:
        score += 2.0
    elif direction == "UNDER" and line_move > 0:
        score -= 2.0

    if pd.notna(clv_line):
        score += clamp(float(clv_line) * 2.0, -6.0, 6.0)

    return clamp(score, -20.0, 20.0)


def calculate_matchup_edge(row: pd.Series) -> float:
    contradiction_tags = tags_from(row.get("ContradictionTags"))
    score = 0.0
    support_weights = {
        "WIND_UNDER_SUPPORT": 5.0,
        "TRAILING_PASS_VOLUME_SUPPORT": 4.0,
        "TRAILING_RB_UNDER_SUPPORT": 4.0,
        "POSITIVE_SCRIPT_RUSH_SUPPORT": 3.0,
        "HIGH_TOTAL_VOLUME_SUPPORT": 3.0,
        "LOW_TOTAL_UNDER_SUPPORT": 3.0,
    }
    risk_weights = {
        "WIND_PASS_OVER_RISK": -7.0,
        "TRAILING_RB_RUSH_OVER_RISK": -5.0,
    }
    for tag, weight in support_weights.items():
        if tag in contradiction_tags:
            score += weight
    for tag, weight in risk_weights.items():
        if tag in contradiction_tags:
            score += weight
    return clamp(score, -10.0, 10.0)


def calculate_game_script_edge(row: pd.Series) -> float:
    tags = tags_from(row.get("GameScriptTags"))
    direction = str(row.get("Direction") or "").upper()
    stat = str(row.get("Stat") or "").upper()
    score = 0.0

    if "HIGH_TOTAL" in tags and direction == "OVER" and any(key in stat for key in ["PASS", "REC"]):
        score += 5.0
    if "LOW_TOTAL" in tags and direction == "UNDER":
        score += 4.0
    if {"PROJECTED_TRAIL", "PROJECTED_BLOWOUT_TRAIL"} & tags:
        if direction == "OVER" and any(key in stat for key in ["PASS", "REC"]):
            score += 5.0
        if direction == "OVER" and stat.startswith("RUSH"):
            score -= 6.0
        if direction == "UNDER" and stat.startswith("RUSH"):
            score += 5.0
    if {"PROJECTED_CLEAR_WIN", "PROJECTED_BLOWOUT_WIN"} & tags:
        if direction == "OVER" and stat.startswith("RUSH"):
            score += 4.0
        if direction == "OVER" and any(key in stat for key in ["PASS YDS", "REC YDS"]):
            score -= 2.0
    if "PROJECTED_TIGHT_GAME" in tags:
        score += 1.0

    return clamp(score, -15.0, 15.0)


def calculate_risk_penalty(row: pd.Series) -> float:
    tags = tags_from(row.get("GameScriptTags"))
    contradiction_tags = tags_from(row.get("ContradictionTags"))
    direction = str(row.get("Direction") or "").upper()
    stat = str(row.get("Stat") or "").upper()
    market_gate = str(row.get("MarketGate") or "CLEAR").upper()
    volatility = str(row.get("VolatilityFlag") or "STABLE").upper()
    penalty = 0.0

    if market_gate == "HOLD":
        penalty -= 8.0
    if volatility == "ELEVATED":
        penalty -= 4.0
    elif volatility == "HIGH":
        penalty -= 8.0
    if "SHORT_REST" in tags:
        penalty -= 3.0
    if "COLD_WEATHER" in tags:
        penalty -= 2.0
    if "WIND_15_PLUS" in tags and direction == "OVER" and any(key in stat for key in ["PASS", "REC"]):
        penalty -= 8.0
    if "WIND_PASS_OVER_RISK" in contradiction_tags:
        penalty -= 5.0
    if "TRAILING_RB_RUSH_OVER_RISK" in contradiction_tags:
        penalty -= 4.0

    return clamp(penalty, -25.0, 0.0)


def score_rows(df: pd.DataFrame) -> pd.DataFrame:
    scored = df.copy()
    scored["ProjectionEdge"] = scored.apply(calculate_projection_edge, axis=1).round(1)
    scored["MarketEdge"] = scored.apply(calculate_market_edge, axis=1).round(1)
    scored["MatchupEdge"] = scored.apply(calculate_matchup_edge, axis=1).round(1)
    scored["GameScriptEdge"] = scored.apply(calculate_game_script_edge, axis=1).round(1)
    scored["RiskPenalty"] = scored.apply(calculate_risk_penalty, axis=1).round(1)
    scored["BK_NFL_EdgeScore"] = (
        scored["ProjectionEdge"]
        + scored["MarketEdge"]
        + scored["MatchupEdge"]
        + scored["GameScriptEdge"]
        + scored["RiskPenalty"]
    ).round(1)
    scored["ModelVersion"] = MODEL_VERSION
    return scored


def main() -> int:
    if not INPUT_PATH.exists():
        raise FileNotFoundError(f"Missing input file: {INPUT_PATH}")
    df = pd.read_csv(INPUT_PATH, low_memory=False)
    if df.empty:
        raise ValueError(f"Input file has no rows: {INPUT_PATH}")
    scored = score_rows(df)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    scored.to_csv(OUTPUT_PATH, index=False)

    resolved = scored[scored["OutcomeState"].isin(["Hit", "Miss"])].copy()
    print(f"Rows scored: {len(scored):,}")
    print(f"Resolved: {len(resolved):,}")
    print(f"Saved: {OUTPUT_PATH}")
    if not resolved.empty:
        top = resolved.sort_values("BK_NFL_EdgeScore", ascending=False).head(10)
        print("Top resolved EdgeScore rows:")
        for _, row in top.iterrows():
            print(
                f"  {row.get('Player')} {row.get('Stat')} {row.get('Direction')} "
                f"{row.get('Line')} | score {row.get('BK_NFL_EdgeScore')} | {row.get('OutcomeState')}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
