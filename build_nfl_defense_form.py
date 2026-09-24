#!/usr/bin/env python3
"""
Build current-season NFL defensive-player form (tackle volume) from nflverse weekly stats.

Our prop model is offense-first, so tackle/sack props were a blind spot. Tackle counts are
ROLE-driven and fairly stable (snap share + how a defense is used), which makes them
projectable off current-season pace -- unlike sacks, which are a low-base-rate coin flip we
deliberately do NOT model as an edge.

This records each defender's 2026 tackle pace (solo/gm and combined = solo+assists /gm),
plus sacks and QB hits for context, so the site can read a tackle prop against real volume.

Output: data/scenarios/nfl_2026_defense.json (small, committable). Run weekly in-season.
Source: nflverse stats_player_week_{season}.parquet. --source <path> builds from a local copy.
"""
from __future__ import annotations
import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
OUT_PATH = BASE_DIR / "data" / "scenarios" / "nfl_2026_defense.json"
STATS_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.parquet"
TEAM_NORM = {"LA": "LAR"}


def _num(df, cols):
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    return df


def build(season: int, source: str | None = None) -> dict:
    tmp = None
    if source:
        df = pd.read_parquet(source)
    else:
        import tempfile
        fd, tmp = tempfile.mkstemp(prefix=f"nfldef_{season}_", suffix=".parquet")
        os.close(fd)
        try:
            urllib.request.urlretrieve(STATS_URL.format(season=season), tmp)
            df = pd.read_parquet(tmp)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

    if "season_type" in df.columns:
        df = df[df["season_type"].astype(str).str.upper().isin(["REG", "REGULAR", ""])]
    df = _num(df, ["def_tackles_solo", "def_tackle_assists", "def_sacks", "def_qb_hits"])
    df = df.dropna(subset=["player_display_name"])
    df["team"] = df["team"].map(lambda t: TEAM_NORM.get(t, t))

    # a defensive-participation mask: had a tackle, assist, sack or QB hit
    df["_def"] = (df["def_tackles_solo"] + df["def_tackle_assists"]
                  + df["def_sacks"] + df["def_qb_hits"])
    d = df[df["_def"] > 0]

    players = {}
    for name, g in d.groupby("player_display_name"):
        gms = int(g["week"].nunique()) or 1
        solo = float(g["def_tackles_solo"].sum())
        ast = float(g["def_tackle_assists"].sum())
        players[str(name)] = {
            "team": str(g["team"].iloc[-1]),
            "pos": str(g["position"].iloc[-1]) if "position" in g.columns else "",
            "games": int(g["week"].nunique()),
            "solo_pg": round(solo / gms, 1),
            "comb_pg": round((solo + ast) / gms, 1),   # solo + assists = betting "Tackles+Assists"
            "solo_tot": solo, "comb_tot": solo + ast,
            "sacks": float(g["def_sacks"].sum()),
            "qb_hits": float(g["def_qb_hits"].sum()),
        }

    return {
        "season": season,
        "weeks": sorted(int(w) for w in d["week"].dropna().unique()),
        "n_players": len(players),
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "players": players,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--source", default=None)
    args = ap.parse_args()
    data = build(args.season, args.source)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Wrote {data['n_players']} defenders, weeks {data['weeks']} -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
