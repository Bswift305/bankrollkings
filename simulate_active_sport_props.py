from __future__ import annotations

from pathlib import Path
from statistics import NormalDist

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
TRACKING_DIR = BASE_DIR / "data" / "tracking"
SPORT_INPUTS = {
    "NBA": TRACKING_DIR / "NBA_AllPropResults.csv",
    "WNBA": TRACKING_DIR / "WNBA_AllPropResults.csv",
    "MLB": TRACKING_DIR / "MLB_AllPropResults_Scored.csv",
}
SUMMARY_PATH = TRACKING_DIR / "Active_Sport_Simulation_Summary.csv"
MIN_PLAYER_SAMPLE = 3
SIM_TRIAL_EQUIVALENT = 5000
MODEL_MODE = "ROLLING_PRIOR_ONLY"
MIN_PRIOR_CALIBRATION_SAMPLE = 20


def to_float(value, default=None):
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return default
    return float(parsed)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _read(path: Path, sport: str) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size <= 2:
        return pd.DataFrame()
    df = pd.read_csv(path, low_memory=False)
    df["Sport"] = sport
    for col in ["Player", "Stat", "Direction", "Line", "ResultValue", "OutcomeState", "Confidence", "MarketGate", "VolatilityFlag", "Method", "MLBEnvironmentTags", "Situations"]:
        if col not in df.columns:
            df[col] = ""
    return df


def _first_valid_datetime(df: pd.DataFrame, columns: list[str]) -> pd.Series:
    result = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    for col in columns:
        if col not in df.columns:
            continue
        parsed = pd.to_datetime(df[col], errors="coerce")
        result = result.fillna(parsed)
    return result


def _distribution_from_history(history: pd.DataFrame) -> tuple[dict, dict]:
    if history.empty:
        return {}, {}
    player_map = {}
    for (player, stat), group in history.groupby(["Player", "Stat"], dropna=False):
        values = group["ResultValueNum"].astype(float)
        if len(values) < MIN_PLAYER_SAMPLE:
            continue
        std = float(values.std(ddof=1))
        mean = float(values.mean())
        if std <= 0:
            std = max(abs(mean) * 0.15, 0.75)
        player_map[(str(player).strip().upper(), str(stat).strip().upper())] = {
            "mean": mean,
            "std": std,
            "sample": int(len(values)),
            "source": "PLAYER",
        }

    stat_map = {}
    for stat, group in history.groupby("Stat", dropna=False):
        values = group["ResultValueNum"].astype(float)
        if len(values) < MIN_PLAYER_SAMPLE:
            continue
        std = float(values.std(ddof=1))
        mean = float(values.mean())
        if std <= 0:
            std = max(abs(mean) * 0.15, 0.75)
        stat_map[str(stat).strip().upper()] = {
            "mean": mean,
            "std": std,
            "sample": int(len(values)),
            "source": "STAT",
        }
    return player_map, stat_map


def _build_prior_hit_context_maps(history: pd.DataFrame) -> dict:
    if history.empty or "HitBinary" not in history.columns:
        return {
            "bucket": {},
            "direction": {},
            "stat": {},
            "sport": {"rate": 50.0, "sample": 0, "source": "NEUTRAL"},
        }

    maps = {"bucket": {}, "direction": {}, "stat": {}}
    for (stat, direction), frame in history.groupby(["Stat", "Direction"], dropna=False):
        if len(frame) >= MIN_PRIOR_CALIBRATION_SAMPLE:
            maps["bucket"][(str(stat).strip().upper(), str(direction).strip().upper())] = {
                "rate": float(frame["HitBinary"].mean()) * 100.0,
                "sample": int(len(frame)),
                "source": "BUCKET",
            }
    for direction, frame in history.groupby("Direction", dropna=False):
        if len(frame) >= MIN_PRIOR_CALIBRATION_SAMPLE:
            maps["direction"][str(direction).strip().upper()] = {
                "rate": float(frame["HitBinary"].mean()) * 100.0,
                "sample": int(len(frame)),
                "source": "DIRECTION",
            }
    for stat, frame in history.groupby("Stat", dropna=False):
        if len(frame) >= MIN_PRIOR_CALIBRATION_SAMPLE:
            maps["stat"][str(stat).strip().upper()] = {
                "rate": float(frame["HitBinary"].mean()) * 100.0,
                "sample": int(len(frame)),
                "source": "STAT",
            }
    maps["sport"] = {
        "rate": float(history["HitBinary"].mean()) * 100.0 if len(history) >= MIN_PRIOR_CALIBRATION_SAMPLE else 50.0,
        "sample": int(len(history)),
        "source": "SPORT" if len(history) >= MIN_PRIOR_CALIBRATION_SAMPLE else "NEUTRAL",
    }
    return maps


def _prior_hit_context(context_maps: dict, stat: str, direction: str) -> dict:
    stat_key = str(stat or "").strip().upper()
    direction_key = str(direction or "").strip().upper()
    return (
        context_maps.get("bucket", {}).get((stat_key, direction_key))
        or context_maps.get("direction", {}).get(direction_key)
        or context_maps.get("stat", {}).get(stat_key)
        or context_maps.get("sport")
        or {"rate": 50.0, "sample": 0, "source": "NEUTRAL"}
    )


def _calibrate_probability(raw_probability: float, prior: dict, sport: str, stat: str = "", direction: str = "") -> tuple[float, str, str]:
    prior_rate = float(prior.get("rate") or 50.0)
    prior_sample = int(prior.get("sample") or 0)
    prior_source = str(prior.get("source") or "NEUTRAL")
    bucket_key = (str(stat or "").strip().upper(), str(direction or "").strip().upper())

    if sport == "NBA":
        calibrated = (raw_probability * 0.30) + (prior_rate * 0.70)
        nba_authority_buckets = {
            ("BLK", "UNDER"),
            ("3PM", "UNDER"),
            ("STL", "OVER"),
            ("PTS", "UNDER"),
        }
        if bucket_key in nba_authority_buckets and prior_sample >= 30 and calibrated >= 56:
            status = "WATCH"
        else:
            status = "CALIBRATION_NEEDED"
    elif sport == "WNBA":
        calibrated = (raw_probability * 0.45) + (prior_rate * 0.55)
        if prior_sample >= 30 and calibrated >= 62:
            status = "LIVE_AUTHORITY"
        elif prior_sample >= 20 and calibrated >= 58:
            status = "WATCH"
        else:
            status = "CALIBRATION_NEEDED"
    elif sport == "MLB":
        calibrated = (raw_probability * 0.50) + (prior_rate * 0.50)
        if prior_sample >= 60 and calibrated >= 62:
            status = "LIVE_AUTHORITY"
        elif prior_sample >= 30 and calibrated >= 58:
            status = "WATCH"
        else:
            status = "CALIBRATION_NEEDED"
    else:
        calibrated = (raw_probability * 0.50) + (prior_rate * 0.50)
        status = "WATCH" if calibrated >= 60 and prior_sample >= 30 else "CALIBRATION_NEEDED"

    detail = f"{prior_source} prior {prior_rate:.1f}% on {prior_sample} rows"
    return round(clamp(calibrated, 0.0, 100.0), 1), status, detail


def _adjust_distribution(row: pd.Series, base: dict, sport: str) -> tuple[float, float, list[str]]:
    mean = float(base.get("mean") or 0.0)
    std = max(float(base.get("std") or 1.0), 0.5)
    tags = []
    stat = str(row.get("Stat") or "").upper()
    direction = str(row.get("Direction") or "").upper()
    context = " | ".join(str(row.get(col) or "") for col in ["Situations", "MLBEnvironmentTags", "Method", "MarketGate", "VolatilityFlag"]).upper()

    if sport in {"NBA", "WNBA"}:
        if any(key in context for key in ["BOOST", "ROLE UP", "TEAMMATE", "CORE ROLE"]):
            mean *= 1.05
            tags.append("ROLE_UP")
        if any(key in context for key in ["ROLE SLIP", "BENCH", "VOLATILE", "MINUTES RISK"]):
            mean *= 0.95
            std *= 1.10
            tags.append("ROLE_RISK")
        if "FLOOR" in context and direction == "UNDER":
            std *= 0.94
            tags.append("FLOOR_UNDER")

    if sport == "MLB":
        if "PITCHER_FRIENDLY" in context and direction == "UNDER":
            mean *= 0.96
            tags.append("PITCHER_FRIENDLY_UNDER")
        if "HITTER_FRIENDLY" in context and direction == "OVER":
            mean *= 1.04
            tags.append("HITTER_FRIENDLY_OVER")
        if "HR_SUPPRESSION" in context and any(key in stat for key in ["HOME", "HR"]):
            mean *= 0.92
            tags.append("HR_SUPPRESSION")

    return max(mean, 0.0), max(std, 0.5), tags


def _simulate_row(row: pd.Series, player_map: dict, stat_map: dict, sport: str, training_count: int, prior: dict) -> dict | None:
    stat = str(row.get("Stat") or "").strip().upper()
    player = str(row.get("Player") or "").strip().upper()
    direction = str(row.get("Direction") or "").strip().upper()
    line = to_float(row.get("Line"))
    if not player or not stat or direction not in {"OVER", "UNDER"} or line is None:
        return None
    base = player_map.get((player, stat)) or stat_map.get(stat)
    if not base:
        return None

    mean, std, tags = _adjust_distribution(row, base, sport)
    dist = NormalDist(mu=mean, sigma=std)
    if direction == "OVER":
        hit_probability = (1.0 - dist.cdf(line)) * 100.0
    else:
        hit_probability = dist.cdf(line) * 100.0
    confidence = to_float(row.get("Confidence"), 50.0) or 50.0
    sim_hit = round(clamp(hit_probability, 0.0, 100.0), 1)
    calibrated_hit, authority_status, calibration_detail = _calibrate_probability(sim_hit, prior, sport, stat, direction)
    return {
        "Sport": sport,
        "AsOfDate": row.get("AsOfDate"),
        "SnapshotDate": row.get("SnapshotDate"),
        "ResultDate": row.get("ResultDate"),
        "Player": row.get("Player"),
        "Team": row.get("Team"),
        "Opponent": row.get("Opponent"),
        "Stat": row.get("Stat"),
        "Direction": direction,
        "Line": line,
        "OutcomeState": row.get("OutcomeState"),
        "ResultValue": row.get("ResultValue"),
        "Confidence": confidence,
        "SimulationMode": MODEL_MODE,
        "TrainingResolvedRows": int(training_count),
        "DistributionSource": base.get("source"),
        "DistributionSample": int(base.get("sample") or 0),
        "SimTrials": SIM_TRIAL_EQUIVALENT,
        "SimMean": round(mean, 2),
        "SimMedian": round(dist.median, 2),
        "SimP25": round(dist.inv_cdf(0.25), 2),
        "SimP75": round(dist.inv_cdf(0.75), 2),
        "SimHitProbability": sim_hit,
        "CalibratedSimHitProbability": calibrated_hit,
        "SimulationAuthority": authority_status,
        "SimulationCalibrationDetail": calibration_detail,
        "SimVolatility": round(std, 2),
        "SimEdgePct": round(calibrated_hit - confidence, 1),
        "SimulationTags": "|".join(tags),
        "ModelVersion": f"{sport}_Simulation_v2_{MODEL_MODE}",
    }


def simulate_sport(sport: str, path: Path) -> pd.DataFrame:
    df = _read(path, sport)
    if df.empty:
        return pd.DataFrame()

    df = df.copy()
    df["AsOfDate"] = _first_valid_datetime(df, ["SnapshotDate", "SavedAt", "ResultDate"])
    df["KnowledgeDate"] = _first_valid_datetime(df, ["ResultDate", "SnapshotDate", "SavedAt"])
    df["ResultValueNum"] = pd.to_numeric(df["ResultValue"], errors="coerce")
    df = df.dropna(subset=["AsOfDate"]).copy()
    if df.empty:
        return pd.DataFrame()

    resolved_history = df[
        df["OutcomeState"].isin(["Hit", "Miss", "Push"]) &
        df["ResultValueNum"].notna() &
        df["KnowledgeDate"].notna()
    ].copy()
    resolved_history["HitBinary"] = resolved_history["OutcomeState"].eq("Hit").astype(int)
    resolved_history = resolved_history.sort_values("KnowledgeDate")
    slate_dates = sorted(df["AsOfDate"].dropna().dt.normalize().unique())
    rows = []

    for slate_date in slate_dates:
        as_of = pd.Timestamp(slate_date)
        prior = resolved_history[resolved_history["KnowledgeDate"] < as_of].copy()
        player_map, stat_map = _distribution_from_history(prior)
        if not player_map and not stat_map:
            continue
        prior_context_maps = _build_prior_hit_context_maps(prior)
        slate = df[df["AsOfDate"].dt.normalize() == as_of].copy()
        for _, row in slate.iterrows():
            prior_context = _prior_hit_context(
                prior_context_maps,
                str(row.get("Stat") or "").strip().upper(),
                str(row.get("Direction") or "").strip().upper(),
            )
            sim = _simulate_row(row, player_map, stat_map, sport, len(prior), prior_context)
            if sim:
                rows.append(sim)
    return pd.DataFrame(rows)


def main() -> int:
    summary_rows = []
    for sport, path in SPORT_INPUTS.items():
        output = simulate_sport(sport, path)
        out_path = TRACKING_DIR / f"{sport}_Simulation_Results.csv"
        output.to_csv(out_path, index=False)
        resolved = output[output["OutcomeState"].isin(["Hit", "Miss"])].copy() if not output.empty else pd.DataFrame()
        authority_col = "CalibratedSimHitProbability" if "CalibratedSimHitProbability" in output.columns else "SimHitProbability"
        high = output[pd.to_numeric(output.get(authority_col), errors="coerce").fillna(0) >= 65].copy() if not output.empty else pd.DataFrame()
        high_resolved = high[high["OutcomeState"].isin(["Hit", "Miss"])].copy() if not high.empty else pd.DataFrame()
        authority_rows = output[output.get("SimulationAuthority", pd.Series(dtype=str)).isin(["LIVE_AUTHORITY", "WATCH"])].copy() if not output.empty else pd.DataFrame()
        authority_resolved = authority_rows[authority_rows["OutcomeState"].isin(["Hit", "Miss"])].copy() if not authority_rows.empty else pd.DataFrame()
        summary_rows.append({
            "Sport": sport,
            "SimulationMode": MODEL_MODE,
            "Rows": int(len(output)),
            "ResolvedRows": int(len(resolved)),
            "HighSimRows": int(len(high)),
            "HighSimResolvedRows": int(len(high_resolved)),
            "HighSimHitRate": round(float(high_resolved["OutcomeState"].eq("Hit").mean()), 4) if not high_resolved.empty else "",
            "AuthorityRows": int(len(authority_rows)),
            "AuthorityResolvedRows": int(len(authority_resolved)),
            "AuthorityHitRate": round(float(authority_resolved["OutcomeState"].eq("Hit").mean()), 4) if not authority_resolved.empty else "",
            "AvgTrainingResolvedRows": round(float(pd.to_numeric(output.get("TrainingResolvedRows"), errors="coerce").mean()), 1) if not output.empty else "",
            "Output": str(out_path.relative_to(BASE_DIR)),
        })
        print(f"{sport}: {len(output):,} simulation rows -> {out_path}")

    summary = pd.DataFrame(summary_rows)
    summary.to_csv(SUMMARY_PATH, index=False)
    print(f"Summary: {SUMMARY_PATH}")
    if not summary.empty:
        print(summary.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
