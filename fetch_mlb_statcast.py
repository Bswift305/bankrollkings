"""
Bankroll Kings - Fetch MLB Statcast Aggregates
==============================================

Pulls public Baseball Savant Statcast aggregate tables through pybaseball and
writes merged hitter/pitcher profile CSVs under data/statcast/.

Examples:
    py -3 fetch_mlb_statcast.py --season 2026
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd
from pybaseball import (
    statcast_batter_exitvelo_barrels,
    statcast_batter_expected_stats,
    statcast_batter_percentile_ranks,
    statcast_pitcher_arsenal_stats,
    statcast_pitcher_exitvelo_barrels,
    statcast_pitcher_expected_stats,
    statcast_pitcher_percentile_ranks,
    statcast_sprint_speed,
)


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "data" / "statcast"


def _player_name_from_last_first(value) -> str:
    text = str(value or "").strip()
    if "," not in text:
        return " ".join(text.split())
    last, first = [part.strip() for part in text.split(",", 1)]
    return " ".join(part for part in [first, last] if part)


def _normalize_player_name(value) -> str:
    return "".join(ch.lower() for ch in str(value or "").strip() if ch.isalnum())


def _prepare_frame(df: pd.DataFrame, prefix: str, *, name_col: str | None = None) -> pd.DataFrame:
    frame = df.copy()
    if "player_id" not in frame.columns:
        return pd.DataFrame(columns=["player_id"])
    frame["player_id"] = pd.to_numeric(frame["player_id"], errors="coerce").astype("Int64")
    if name_col and name_col in frame.columns:
        frame["Player"] = frame[name_col].map(_player_name_from_last_first)
    elif "player_name" in frame.columns:
        frame["Player"] = frame["player_name"].map(_player_name_from_last_first)
    elif {"first_name", "last_name"}.issubset(frame.columns):
        frame["Player"] = (frame["first_name"].fillna("").astype(str).str.strip() + " " + frame["last_name"].fillna("").astype(str).str.strip()).str.strip()
    else:
        frame["Player"] = ""
    keep = ["player_id", "Player"]
    rename = {}
    for col in frame.columns:
        if col in {"player_id", "Player"}:
            continue
        rename[col] = f"{prefix}{col}"
        keep.append(col)
    frame = frame[keep].rename(columns=rename)
    return frame.drop_duplicates(subset=["player_id"], keep="last")


def _merge_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    merged = pd.DataFrame()
    for frame in frames:
        if frame is None or frame.empty or "player_id" not in frame.columns:
            continue
        if merged.empty:
            merged = frame.copy()
        else:
            merged = merged.merge(frame, on="player_id", how="outer", suffixes=("", "_dup"))
            player_cols = [col for col in merged.columns if col == "Player" or col.startswith("Player_dup")]
            if player_cols:
                base = merged.get("Player", pd.Series(dtype=str)).fillna("").astype(str)
                for col in player_cols:
                    if col == "Player":
                        continue
                    base = base.where(base.str.strip() != "", merged[col].fillna("").astype(str))
                merged["Player"] = base
                merged = merged.drop(columns=[col for col in player_cols if col != "Player"], errors="ignore")
    if merged.empty:
        return merged
    merged["Player"] = merged["Player"].fillna("").astype(str).str.strip()
    merged["PlayerKey"] = merged["Player"].map(_normalize_player_name)
    return merged.sort_values(["Player"]).reset_index(drop=True)


def _pitcher_arsenal_summary(arsenal: pd.DataFrame) -> pd.DataFrame:
    if arsenal is None or arsenal.empty or "player_id" not in arsenal.columns:
        return pd.DataFrame(columns=["player_id"])
    df = arsenal.copy()
    df["player_id"] = pd.to_numeric(df["player_id"], errors="coerce").astype("Int64")
    for col in ["pitches", "pitch_usage", "whiff_percent", "k_percent", "run_value_per_100", "hard_hit_percent"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    rows = []
    for player_id, group in df.groupby("player_id", dropna=True):
        group = group.copy()
        player = ""
        if {"first_name", "last_name"}.issubset(group.columns):
            first = str(group["first_name"].dropna().iloc[0]) if not group["first_name"].dropna().empty else ""
            last = str(group["last_name"].dropna().iloc[0]) if not group["last_name"].dropna().empty else ""
            player = f"{first} {last}".strip()
        usage_sorted = group.sort_values("pitch_usage", ascending=False) if "pitch_usage" in group.columns else group
        best_whiff = group.sort_values("whiff_percent", ascending=False).head(1)
        rows.append({
            "player_id": player_id,
            "Player": player,
            "ArsenalPitchCount": int(len(group)),
            "PrimaryPitch": str(usage_sorted.iloc[0].get("pitch_name") or usage_sorted.iloc[0].get("pitch_type") or "") if not usage_sorted.empty else "",
            "PrimaryPitchUsage": round(float(usage_sorted.iloc[0].get("pitch_usage")), 1) if not usage_sorted.empty and pd.notna(usage_sorted.iloc[0].get("pitch_usage")) else None,
            "BestWhiffPitch": str(best_whiff.iloc[0].get("pitch_name") or best_whiff.iloc[0].get("pitch_type") or "") if not best_whiff.empty else "",
            "BestWhiffPct": round(float(best_whiff.iloc[0].get("whiff_percent")), 1) if not best_whiff.empty and pd.notna(best_whiff.iloc[0].get("whiff_percent")) else None,
            "ArsenalAvgWhiffPct": round(float(group["whiff_percent"].mean()), 1) if "whiff_percent" in group.columns and group["whiff_percent"].notna().any() else None,
            "ArsenalAvgKPct": round(float(group["k_percent"].mean()), 1) if "k_percent" in group.columns and group["k_percent"].notna().any() else None,
            "ArsenalAvgHardHitPct": round(float(group["hard_hit_percent"].mean()), 1) if "hard_hit_percent" in group.columns and group["hard_hit_percent"].notna().any() else None,
        })
    return pd.DataFrame(rows)


def fetch_statcast_profiles(season: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    print(f"Fetching Statcast hitter tables for {season}...")
    batter_expected = statcast_batter_expected_stats(year=season)
    batter_barrels = statcast_batter_exitvelo_barrels(year=season)
    batter_percentiles = statcast_batter_percentile_ranks(year=season)
    sprint = statcast_sprint_speed(year=season)

    print(f"Fetching Statcast pitcher tables for {season}...")
    pitcher_expected = statcast_pitcher_expected_stats(year=season)
    pitcher_barrels = statcast_pitcher_exitvelo_barrels(year=season)
    pitcher_percentiles = statcast_pitcher_percentile_ranks(year=season)
    pitcher_arsenal = statcast_pitcher_arsenal_stats(year=season)

    hitter = _merge_frames([
        _prepare_frame(batter_expected, "Expected_", name_col="last_name, first_name"),
        _prepare_frame(batter_barrels, "Barrel_", name_col="last_name, first_name"),
        _prepare_frame(batter_percentiles, "Percentile_", name_col="player_name"),
        _prepare_frame(sprint, "Sprint_", name_col="last_name, first_name"),
    ])
    pitcher = _merge_frames([
        _prepare_frame(pitcher_expected, "Expected_", name_col="last_name, first_name"),
        _prepare_frame(pitcher_barrels, "Barrel_", name_col="last_name, first_name"),
        _prepare_frame(pitcher_percentiles, "Percentile_", name_col="player_name"),
        _pitcher_arsenal_summary(pitcher_arsenal),
    ])
    fetched_at = datetime.now().astimezone().isoformat(timespec="seconds")
    for frame in [hitter, pitcher]:
        if not frame.empty:
            frame.insert(0, "Season", season)
            frame.insert(1, "FetchedAt", fetched_at)
    return hitter, pitcher


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch MLB Statcast aggregate profile data")
    parser.add_argument("--season", type=int, default=2026, help="MLB season to fetch")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    hitter, pitcher = fetch_statcast_profiles(args.season)
    hitter_path = OUTPUT_DIR / f"MLB_Statcast_Hitters_{args.season}.csv"
    pitcher_path = OUTPUT_DIR / f"MLB_Statcast_Pitchers_{args.season}.csv"
    hitter.to_csv(hitter_path, index=False)
    pitcher.to_csv(pitcher_path, index=False)
    print(f"Saved hitters: {len(hitter):,} rows -> {hitter_path}")
    print(f"Saved pitchers: {len(pitcher):,} rows -> {pitcher_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
