#!/usr/bin/env python3
"""
Build current-season NFL team form (offense + defense) from real nflverse weekly stats.

The 2026 season is live, so the site should reason off how each team is ACTUALLY playing
NOW -- not last year's profile. This aggregates the current season's player-week box scores
into per-team splits and, crucially, DEFENSIVE splits (what each defense has allowed, keyed
off opponent_team) plus pass-rush production. It then ranks all 32 defenses on the metrics
that drive a game read: run defense (yds/carry + yds/game allowed), pass defense (yds/game
allowed), and pressure (sacks + QB hits).

This is the NFL sibling of cfb_current_form's data step. Run weekly in-season.
Output: data/scenarios/nfl_2026_form.json (small, committable -- like cfb_2026_results.json).

Source: nflverse stats_player_week_{season}.parquet (same feed the receiver profile uses).
Pass --source <path.parquet> to build from a local copy instead of downloading.
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
OUT_PATH = BASE_DIR / "data" / "scenarios" / "nfl_2026_form.json"
STATS_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.parquet"

# nflverse uses "LA" for the Rams; the odds/props feeds use "LAR". Normalize to the feed code.
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
        fd, tmp = tempfile.mkstemp(prefix=f"nflform_{season}_", suffix=".parquet")
        os.close(fd)
        try:
            urllib.request.urlretrieve(STATS_URL.format(season=season), tmp)
            df = pd.read_parquet(tmp)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

    # regular season only
    if "season_type" in df.columns:
        df = df[df["season_type"].astype(str).str.upper().isin(["REG", "REGULAR", ""])]
    df = _num(df, [
        "carries", "rushing_yards", "rushing_tds", "passing_yards", "passing_tds",
        "attempts", "passing_air_yards", "sacks_suffered", "def_sacks", "def_qb_hits",
        "def_interceptions",
    ])
    df = df.dropna(subset=["team", "opponent_team"])
    df["team"] = df["team"].map(lambda t: TEAM_NORM.get(t, t))
    df["opponent_team"] = df["opponent_team"].map(lambda t: TEAM_NORM.get(t, t))

    teams = sorted(set(df["team"]) | set(df["opponent_team"]))
    weeks = sorted(int(w) for w in df["week"].dropna().unique())
    rec = {}
    for T in teams:
        opp = df[df["opponent_team"] == T]   # offenses that faced T -> what T allowed
        own = df[df["team"] == T]            # T's own box (defensive counting + offense)
        gms = int(own["week"].nunique()) or 1
        car_a = opp["carries"].sum()
        rush_a = opp["rushing_yards"].sum()
        car_o = own["carries"].sum()
        # Whose passing form this is: the primary passer (most attempts) + his aDOT.
        # Box-score form can't see a QB change, so a returning starter must be a
        # VISIBLE caveat on the card -- form built on a checkdown backup understates a
        # team that's about to get its downfield starter back.
        passers = own[own["attempts"] > 0]
        qb1 = qb1_att = qb1_adot = None
        if len(passers):
            by_qb = passers.groupby("player_display_name").agg(
                att=("attempts", "sum"), ay=("passing_air_yards", "sum")).reset_index()
            top = by_qb.sort_values("att", ascending=False).iloc[0]
            qb1 = str(top["player_display_name"])
            qb1_att = int(top["att"])
            qb1_adot = round(top["ay"] / top["att"], 1) if top["att"] else None
        rec[T] = {
            "games": int(own["week"].nunique()),
            "qb1": qb1, "qb1_att": qb1_att, "qb1_adot": qb1_adot,
            # defense: what T allows
            "def_sacks": float(own["def_sacks"].sum()),
            "def_qb_hits": float(own["def_qb_hits"].sum()),
            "def_ints": float(own["def_interceptions"].sum()),
            "rush_ypc_allowed": round(rush_a / car_a, 2) if car_a else 0.0,
            "rush_ypg_allowed": round(rush_a / gms, 1),
            "pass_ypg_allowed": round(opp["passing_yards"].sum() / gms, 1),
            "rush_td_allowed": float(opp["rushing_tds"].sum()),
            "pass_td_allowed": float(opp["passing_tds"].sum()),
            # offense: what T does
            "rush_ypg": round(own["rushing_yards"].sum() / gms, 1),
            "pass_ypg": round(own["passing_yards"].sum() / gms, 1),
            "rush_ypc": round(own["rushing_yards"].sum() / car_o, 2) if car_o else 0.0,
            "sacks_allowed": float(own["sacks_suffered"].sum()),
        }

    # league ranks (1 = best defense) on the metrics a game read turns on
    frame = pd.DataFrame(rec).T
    rank_specs = [
        ("def_sacks", False, "sack_rank"),
        ("def_qb_hits", False, "qbhit_rank"),
        ("rush_ypc_allowed", True, "rush_ypc_rank"),
        ("rush_ypg_allowed", True, "rush_ypg_rank"),
        ("pass_ypg_allowed", True, "pass_ypg_rank"),
    ]
    for col, asc, name in rank_specs:
        ranks = frame[col].rank(ascending=asc, method="min").astype(int)
        for T in rec:
            rec[T][name] = int(ranks[T])

    return {
        "season": season,
        "weeks": weeks,
        "n_teams": len(teams),
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "league_avg": {
            "rush_ypc_allowed": round(frame["rush_ypc_allowed"].mean(), 2),
            "rush_ypg_allowed": round(frame["rush_ypg_allowed"].mean(), 1),
            "pass_ypg_allowed": round(frame["pass_ypg_allowed"].mean(), 1),
            "def_sacks": round(frame["def_sacks"].mean(), 1),
        },
        "teams": rec,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--source", default=None, help="local parquet to build from instead of downloading")
    args = ap.parse_args()
    data = build(args.season, args.source)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Wrote {data['n_teams']} teams, weeks {data['weeks']} -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
