from __future__ import annotations

from pathlib import Path

import pandas as pd

from services.ngs_loader import build_ngs_prop_signal


BASE_DIR = Path(__file__).resolve().parent
SCORED_INPUT_PATH = BASE_DIR / "data" / "tracking" / "NFL_AllPropResults_Scored.csv"
RAW_INPUT_PATH = BASE_DIR / "data" / "tracking" / "NFL_AllPropResults.csv"
PROFILE_PATH = BASE_DIR / "data" / "tracking" / "NFL_Player_Hit_Profiles.csv"
OUTPUT_PATH = BASE_DIR / "data" / "tracking" / "NFL_AllPropResults_Scored.csv"
MODEL_VERSION = "NFL_PropScore_v1"


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


def load_profiles() -> dict[tuple[str, str, str], dict]:
    if not PROFILE_PATH.exists():
        return {}
    try:
        profiles = pd.read_csv(PROFILE_PATH, low_memory=False)
    except Exception:
        return {}
    lookup = {}
    for _, row in profiles.iterrows():
        key = (
            str(row.get("Player") or "").strip().upper(),
            str(row.get("Stat") or "").strip().upper(),
            str(row.get("Direction") or "").strip().upper(),
        )
        if not all(key):
            continue
        lookup[key] = row.to_dict()
    return lookup


def profile_for(row: pd.Series, profiles: dict[tuple[str, str, str], dict]) -> dict:
    key = (
        str(row.get("Player") or "").strip().upper(),
        str(row.get("Stat") or "").strip().upper(),
        str(row.get("Direction") or "").strip().upper(),
    )
    return profiles.get(key, {})


def calculate_usage_stability(row: pd.Series, profile: dict) -> float:
    role = str(row.get("RoleLabel") or "").upper()
    resolved = to_float(profile.get("Resolved"), 0.0)
    hit_rate = to_float(profile.get("HitRate"), 50.0)
    reliability = str(profile.get("Reliability") or "").upper()

    score = 0.0
    if reliability == "ANCHOR":
        score += 12.0
    elif reliability == "WATCH":
        score += 8.0
    elif reliability == "DEVELOPING":
        score += 3.0
    elif reliability == "AVOID":
        score -= 10.0

    if resolved >= 20:
        score += 4.0
    elif resolved >= 10:
        score += 2.0
    elif resolved < 5:
        score -= 4.0

    score += clamp((hit_rate - 50.0) * 0.2, -6.0, 6.0)

    if role in {"PASSING", "RUSHING", "RECEIVING"}:
        score += 1.0

    return clamp(score, -15.0, 20.0)


def calculate_matchup_advantage(row: pd.Series) -> float:
    contradiction_tags = tags_from(row.get("ContradictionTags"))
    role = str(row.get("RoleLabel") or "").upper()
    score = 0.0
    weights = {
        "WIND_UNDER_SUPPORT": 7.0,
        "TRAILING_PASS_VOLUME_SUPPORT": 6.0,
        "TRAILING_RB_UNDER_SUPPORT": 6.0,
        "POSITIVE_SCRIPT_RUSH_SUPPORT": 5.0,
        "HIGH_TOTAL_VOLUME_SUPPORT": 4.0,
        "LOW_TOTAL_UNDER_SUPPORT": 4.0,
        "WIND_PASS_OVER_RISK": -9.0,
        "TRAILING_RB_RUSH_OVER_RISK": -8.0,
    }
    for tag, weight in weights.items():
        if tag in contradiction_tags:
            score += weight

    if role == "RECEIVING" and "WIND_PASS_OVER_RISK" in contradiction_tags:
        score -= 2.0
    if role == "RUSHING" and "POSITIVE_SCRIPT_RUSH_SUPPORT" in contradiction_tags:
        score += 2.0

    return clamp(score, -20.0, 20.0)


def calculate_game_script_fit(row: pd.Series) -> float:
    tags = tags_from(row.get("GameScriptTags"))
    direction = str(row.get("Direction") or "").upper()
    stat = str(row.get("Stat") or "").upper()
    score = 0.0

    if {"PROJECTED_TRAIL", "PROJECTED_BLOWOUT_TRAIL"} & tags:
        if direction == "OVER" and any(key in stat for key in ["PASS", "REC"]):
            score += 8.0
        if direction == "UNDER" and stat.startswith("RUSH"):
            score += 8.0
        if direction == "OVER" and stat.startswith("RUSH"):
            score -= 10.0

    if {"PROJECTED_CLEAR_WIN", "PROJECTED_BLOWOUT_WIN"} & tags:
        if direction == "OVER" and stat.startswith("RUSH"):
            score += 6.0
        if direction == "OVER" and any(key in stat for key in ["PASS YDS", "REC YDS"]):
            score -= 4.0

    if "HIGH_TOTAL" in tags and direction == "OVER":
        score += 4.0
    if "LOW_TOTAL" in tags and direction == "UNDER":
        score += 4.0
    if "PROJECTED_TIGHT_GAME" in tags:
        score += 2.0

    return clamp(score, -20.0, 20.0)


def calculate_line_value(row: pd.Series, profile: dict) -> float:
    confidence = to_float(row.get("Confidence"), 50.0)
    market_gate = str(row.get("MarketGate") or "CLEAR").upper()
    market_price = to_float(row.get("MarketPrice"), 0.0)
    avg_line = to_float(profile.get("AvgLine"), 0.0)
    line = to_float(row.get("Line"), 0.0)
    direction = str(row.get("Direction") or "").upper()

    score = clamp((confidence - 50.0) * 0.8, -10.0, 10.0)
    if market_gate == "CLEAR":
        score += 4.0
    elif market_gate == "HOLD":
        score -= 10.0

    if market_price <= -200:
        score += 2.0
    elif market_price >= 150:
        score -= 2.0

    if avg_line and line:
        if direction == "OVER" and line < avg_line:
            score += clamp((avg_line - line) * 1.2, 0.0, 6.0)
        if direction == "UNDER" and line > avg_line:
            score += clamp((line - avg_line) * 1.2, 0.0, 6.0)

    return clamp(score, -20.0, 20.0)


def calculate_volatility_penalty(row: pd.Series, profile: dict) -> float:
    tags = tags_from(row.get("GameScriptTags"))
    contradiction_tags = tags_from(row.get("ContradictionTags"))
    volatility = str(row.get("VolatilityFlag") or "STABLE").upper()
    reliability = str(profile.get("Reliability") or "").upper()
    direction = str(row.get("Direction") or "").upper()
    stat = str(row.get("Stat") or "").upper()
    penalty = 0.0

    if volatility == "ELEVATED":
        penalty -= 5.0
    elif volatility == "HIGH":
        penalty -= 10.0
    if reliability == "AVOID":
        penalty -= 10.0
    if "SHORT_REST" in tags:
        penalty -= 3.0
    if "WIND_15_PLUS" in tags and direction == "OVER" and any(key in stat for key in ["PASS", "REC"]):
        penalty -= 10.0
    if "WIND_PASS_OVER_RISK" in contradiction_tags:
        penalty -= 5.0
    if "TRAILING_RB_RUSH_OVER_RISK" in contradiction_tags:
        penalty -= 5.0

    return clamp(penalty, -25.0, 0.0)


def calculate_ngs_modifier(row: pd.Series) -> float:
    signal = build_ngs_prop_signal(
        str(row.get("Player") or ""),
        str(row.get("Stat") or ""),
        str(row.get("Direction") or "OVER"),
    )
    if not signal.get("available"):
        return 0.0
    return clamp(to_float(signal.get("score_delta"), 0.0), -6.0, 6.0)


def calculate_ngs_note(row: pd.Series) -> str:
    signal = build_ngs_prop_signal(
        str(row.get("Player") or ""),
        str(row.get("Stat") or ""),
        str(row.get("Direction") or "OVER"),
    )
    if not signal.get("available"):
        return ""
    tags = " | ".join(signal.get("tags") or [])
    note = str(signal.get("note") or "").strip()
    return " - ".join(part for part in [tags, note] if part)


def ngs_signal_for_row(row: pd.Series, cache: dict[tuple[str, str, str], dict]) -> dict:
    key = (
        str(row.get("Player") or "").strip(),
        str(row.get("Stat") or "").strip(),
        str(row.get("Direction") or "OVER").strip().upper(),
    )
    if key not in cache:
        cache[key] = build_ngs_prop_signal(*key)
    return cache[key]


def score_rows(df: pd.DataFrame) -> pd.DataFrame:
    profiles = load_profiles()
    scored = df.copy()
    profile_cache = [profile_for(row, profiles) for _, row in scored.iterrows()]
    scored["UsageStability"] = [round(calculate_usage_stability(row, profile), 1) for (_, row), profile in zip(scored.iterrows(), profile_cache)]
    scored["MatchupAdvantage"] = [round(calculate_matchup_advantage(row), 1) for _, row in scored.iterrows()]
    scored["GameScriptFit"] = [round(calculate_game_script_fit(row), 1) for _, row in scored.iterrows()]
    scored["LineValue"] = [round(calculate_line_value(row, profile), 1) for (_, row), profile in zip(scored.iterrows(), profile_cache)]
    scored["VolatilityPenalty"] = [round(calculate_volatility_penalty(row, profile), 1) for (_, row), profile in zip(scored.iterrows(), profile_cache)]
    ngs_cache: dict[tuple[str, str, str], dict] = {}
    ngs_signals = [ngs_signal_for_row(row, ngs_cache) for _, row in scored.iterrows()]
    scored["NGSModifier"] = [
        round(clamp(to_float(signal.get("score_delta"), 0.0), -6.0, 6.0), 1)
        if signal.get("available") else 0.0
        for signal in ngs_signals
    ]
    scored["NGSNote"] = [
        " - ".join(part for part in [" | ".join(signal.get("tags") or []), str(signal.get("note") or "").strip()] if part)
        if signal.get("available") else ""
        for signal in ngs_signals
    ]
    scored["BK_NFL_PropScore"] = (
        scored["UsageStability"]
        + scored["MatchupAdvantage"]
        + scored["GameScriptFit"]
        + scored["LineValue"]
        + scored["VolatilityPenalty"]
        + scored["NGSModifier"]
    ).round(1)
    scored["PropModelVersion"] = MODEL_VERSION
    return scored


def main() -> int:
    input_path = SCORED_INPUT_PATH if SCORED_INPUT_PATH.exists() else RAW_INPUT_PATH
    if not input_path.exists():
        raise FileNotFoundError(f"Missing input file: {input_path}")
    df = pd.read_csv(input_path, low_memory=False)
    if df.empty:
        raise ValueError(f"Input file has no rows: {input_path}")
    scored = score_rows(df)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    scored.to_csv(OUTPUT_PATH, index=False)

    resolved = scored[scored["OutcomeState"].isin(["Hit", "Miss"])].copy()
    print(f"Rows prop-scored: {len(scored):,}")
    print(f"Resolved: {len(resolved):,}")
    print(f"Saved: {OUTPUT_PATH}")
    if not resolved.empty:
        for label, sub in [
            ("25+", resolved[pd.to_numeric(resolved["BK_NFL_PropScore"], errors="coerce") >= 25]),
            ("15-25", resolved[(pd.to_numeric(resolved["BK_NFL_PropScore"], errors="coerce") >= 15) & (pd.to_numeric(resolved["BK_NFL_PropScore"], errors="coerce") < 25)]),
            ("0-15", resolved[(pd.to_numeric(resolved["BK_NFL_PropScore"], errors="coerce") >= 0) & (pd.to_numeric(resolved["BK_NFL_PropScore"], errors="coerce") < 15)]),
            ("<0", resolved[pd.to_numeric(resolved["BK_NFL_PropScore"], errors="coerce") < 0]),
        ]:
            hit_rate = round(float(sub["OutcomeState"].eq("Hit").mean()) * 100, 1) if len(sub) else None
            print(f"{label}: {len(sub):,} rows | {hit_rate}% hit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
