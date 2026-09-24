#!/usr/bin/env python3
"""
Build the receiver-archetype profile that powers the archetype gate.

The Week-1-3 2026 read exposed a PropScore gap: it rewards target volume/usage but
ignores receiver ARCHETYPE. A deep threat (high average depth of target) catches few
balls on downfield targets, so his RECEPTION count is volatile and sits right on a low
line -- a coin flip dressed up as a top play (Jameson Williams: ~13.6 aDOT, 4 then 2
catches on a 3.5 line). His edge is in YARDS, not catches.

This records each pass-catcher's season aDOT (air yards / target), average catches, and
target share from real nflverse weekly stats, so the gate can flag receptions props on
deep-threat archetypes. Run weekly in-season. Output: data/rosters/NFL_ReceiverProfile.csv
"""
from __future__ import annotations
import argparse
import urllib.request
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
OUT_PATH = BASE_DIR / "data" / "rosters" / "NFL_ReceiverProfile.csv"
STATS_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.parquet"
MIN_TARGETS = 8  # need a real sample before trusting an aDOT read


def build(season: int) -> pd.DataFrame:
    url = STATS_URL.format(season=season)
    tmp = BASE_DIR / "data" / "rosters" / f"_recv_{season}.parquet"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, tmp)
    df = pd.read_parquet(tmp)
    for c in ("targets", "receptions", "receiving_air_yards", "target_share"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["player_display_name"])
    g = df.groupby("player_display_name").agg(
        games=("week", "nunique"),
        targets=("targets", "sum"),
        receptions=("receptions", "sum"),
        air_yards=("receiving_air_yards", "sum"),
        target_share=("target_share", "mean"),
    ).reset_index().rename(columns={"player_display_name": "Player"})
    g = g[g["targets"] >= MIN_TARGETS].copy()
    g["aDOT"] = (g["air_yards"] / g["targets"]).round(1)
    g["avg_rec"] = (g["receptions"] / g["games"]).round(1)
    g["target_share"] = (g["target_share"] * 100).round(1)
    return g[["Player", "games", "targets", "receptions", "avg_rec", "aDOT", "target_share"]].sort_values("aDOT", ascending=False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    args = ap.parse_args()
    out = build(args.season)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_PATH, index=False)
    print(f"Wrote {len(out)} receivers -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
