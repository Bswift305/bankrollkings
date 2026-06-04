from __future__ import annotations

from pathlib import Path
from statistics import NormalDist

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
INPUT_PATH = BASE_DIR / "data" / "tracking" / "NFL_AllPropResults_Scored.csv"
FALLBACK_INPUT_PATH = BASE_DIR / "data" / "tracking" / "NFL_AllPropResults.csv"
OUTPUT_PATH = BASE_DIR / "data" / "tracking" / "NFL_Simulation_Results.csv"
SUPPORTED_STATS = {"PASS YDS", "RUSH YDS", "RECEPTIONS", "REC YDS"}
SIM_TRIAL_EQUIVALENT = 5000


def to_float(value, default: float | None = None) -> float | None:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return default
    return float(parsed)


def tags_from(value) -> set[str]:
    text = str(value or "").upper()
    return {part.strip() for part in text.split("|") if part.strip()}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def build_distribution_maps(df: pd.DataFrame) -> tuple[dict, dict]:
    resolved = df[df["OutcomeState"].isin(["Hit", "Miss", "Push"])].copy()
    resolved["ResultValueNum"] = pd.to_numeric(resolved.get("ResultValue"), errors="coerce")
    resolved = resolved.dropna(subset=["ResultValueNum"]).copy()
    resolved["StatUpper"] = resolved["Stat"].fillna("").astype(str).str.upper()
    resolved = resolved[resolved["StatUpper"].isin(SUPPORTED_STATS)].copy()

    player_map = {}
    for (player, stat), group in resolved.groupby(["Player", "StatUpper"], dropna=False):
        values = group["ResultValueNum"].astype(float)
        if len(values) < 3:
            continue
        std = float(values.std(ddof=1))
        if std <= 0:
            std = max(float(values.mean()) * 0.15, 1.0)
        player_map[(str(player).strip().upper(), str(stat).strip().upper())] = {
            "mean": float(values.mean()),
            "std": std,
            "sample": int(len(values)),
        }

    stat_map = {}
    for stat, group in resolved.groupby("StatUpper", dropna=False):
        values = group["ResultValueNum"].astype(float)
        if len(values) < 3:
            continue
        std = float(values.std(ddof=1))
        if std <= 0:
            std = max(float(values.mean()) * 0.15, 1.0)
        stat_map[str(stat).strip().upper()] = {
            "mean": float(values.mean()),
            "std": std,
            "sample": int(len(values)),
        }
    return player_map, stat_map


def adjusted_distribution(row: pd.Series, base: dict) -> tuple[float, float]:
    mean = float(base.get("mean") or 0.0)
    std = max(float(base.get("std") or 1.0), 0.5)
    stat = str(row.get("Stat") or "").upper()
    tags = tags_from(row.get("GameScriptTags"))
    contradiction_tags = tags_from(row.get("ContradictionTags"))

    if {"PROJECTED_TRAIL", "PROJECTED_BLOWOUT_TRAIL"} & tags:
        if any(key in stat for key in ["PASS", "REC"]):
            mean *= 1.10
        if stat.startswith("RUSH"):
            mean *= 0.88
    if {"PROJECTED_CLEAR_WIN", "PROJECTED_BLOWOUT_WIN"} & tags:
        if stat.startswith("RUSH"):
            mean *= 1.08
        if any(key in stat for key in ["PASS YDS", "REC YDS"]):
            mean *= 0.95
    if "HIGH_TOTAL" in tags:
        mean *= 1.04
    if "LOW_TOTAL" in tags:
        mean *= 0.96
    if "WIND_15_PLUS" in tags and any(key in stat for key in ["PASS", "REC"]):
        mean *= 0.90
        std *= 1.15
    if "TRAILING_PASS_VOLUME_SUPPORT" in contradiction_tags:
        mean *= 1.06
    if "WIND_UNDER_SUPPORT" in contradiction_tags:
        mean *= 0.94
    if "TRAILING_RB_RUSH_OVER_RISK" in contradiction_tags:
        mean *= 0.90

    return max(mean, 0.0), max(std, 0.5)


def simulation_row(row: pd.Series, player_map: dict, stat_map: dict) -> dict | None:
    stat = str(row.get("Stat") or "").strip().upper()
    if stat not in SUPPORTED_STATS:
        return None
    line = to_float(row.get("Line"))
    if line is None:
        return None
    player = str(row.get("Player") or "").strip().upper()
    base = player_map.get((player, stat)) or stat_map.get(stat)
    if not base:
        return None

    mean, std = adjusted_distribution(row, base)
    dist = NormalDist(mu=mean, sigma=std)
    direction = str(row.get("Direction") or "").strip().upper()
    if direction == "OVER":
        hit_probability = (1.0 - dist.cdf(line)) * 100.0
    elif direction == "UNDER":
        hit_probability = dist.cdf(line) * 100.0
    else:
        return None

    confidence = to_float(row.get("Confidence"), 50.0) or 50.0
    sim_hit = round(clamp(hit_probability, 0.0, 100.0), 1)
    return {
        "SnapshotDate": row.get("SnapshotDate"),
        "Season": row.get("Season"),
        "Week": row.get("Week"),
        "Player": row.get("Player"),
        "Team": row.get("Team"),
        "Opponent": row.get("Opponent"),
        "Stat": row.get("Stat"),
        "Direction": direction,
        "Line": line,
        "OutcomeState": row.get("OutcomeState"),
        "ResultValue": row.get("ResultValue"),
        "Confidence": confidence,
        "BK_NFL_PropScore": row.get("BK_NFL_PropScore"),
        "BK_NFL_EdgeScore": row.get("BK_NFL_EdgeScore"),
        "GameScriptTags": row.get("GameScriptTags"),
        "ContradictionTags": row.get("ContradictionTags"),
        "DistributionSample": int(base.get("sample") or 0),
        "SimTrials": SIM_TRIAL_EQUIVALENT,
        "SimMean": round(mean, 1),
        "SimMedian": round(dist.median, 1),
        "SimP25": round(dist.inv_cdf(0.25), 1),
        "SimP75": round(dist.inv_cdf(0.75), 1),
        "SimHitProbability": sim_hit,
        "SimVolatility": round(std, 1),
        "SimEdgePct": round(sim_hit - confidence, 1),
    }


def main() -> int:
    input_path = INPUT_PATH if INPUT_PATH.exists() else FALLBACK_INPUT_PATH
    if not input_path.exists():
        raise FileNotFoundError(f"Missing input file: {input_path}")
    df = pd.read_csv(input_path, low_memory=False)
    if df.empty:
        raise ValueError(f"Input file has no rows: {input_path}")

    player_map, stat_map = build_distribution_maps(df)
    rows = []
    for _, row in df.iterrows():
        sim = simulation_row(row, player_map, stat_map)
        if sim:
            rows.append(sim)

    output = pd.DataFrame(rows)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(OUTPUT_PATH, index=False)

    resolved = output[output["OutcomeState"].isin(["Hit", "Miss"])].copy() if not output.empty else pd.DataFrame()
    print(f"Simulation rows: {len(output):,}")
    print(f"Resolved simulation rows: {len(resolved):,}")
    print(f"Saved: {OUTPUT_PATH}")
    if not resolved.empty:
        for label, sub in [
            ("70+ sim", resolved[pd.to_numeric(resolved["SimHitProbability"], errors="coerce") >= 70]),
            ("60-70 sim", resolved[(pd.to_numeric(resolved["SimHitProbability"], errors="coerce") >= 60) & (pd.to_numeric(resolved["SimHitProbability"], errors="coerce") < 70)]),
            ("50-60 sim", resolved[(pd.to_numeric(resolved["SimHitProbability"], errors="coerce") >= 50) & (pd.to_numeric(resolved["SimHitProbability"], errors="coerce") < 60)]),
            ("<50 sim", resolved[pd.to_numeric(resolved["SimHitProbability"], errors="coerce") < 50]),
        ]:
            hit_rate = round(float(sub["OutcomeState"].eq("Hit").mean()) * 100, 1) if len(sub) else None
            print(f"{label}: {len(sub):,} rows | {hit_rate}% actual")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
