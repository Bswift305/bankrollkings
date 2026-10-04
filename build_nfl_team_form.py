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
        "def_interceptions", "fumble_recovery_opp",
        "passing_interceptions", "rushing_fumbles_lost", "receiving_fumbles_lost",
        "sack_fumbles_lost",
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
        opps_faced = [str(o) for o in own.groupby("week")["opponent_team"].first().tolist()]
        rec[T] = {
            "games": int(own["week"].nunique()),
            "opps_faced": opps_faced,
            "qb1": qb1, "qb1_att": qb1_att, "qb1_adot": qb1_adot,
            # defense: what T allows
            "def_sacks": float(own["def_sacks"].sum()),
            "def_qb_hits": float(own["def_qb_hits"].sum()),
            "def_ints": float(own["def_interceptions"].sum()),
            "rush_ypc_allowed": round(rush_a / car_a, 2) if car_a else 0.0,
            "rush_ypg_allowed": round(rush_a / gms, 1),
            "pass_ypg_allowed": round(opp["passing_yards"].sum() / gms, 1),
            # per-DROPBACK efficiency allowed (Averaging Audit A2): per-game pass yds
            # allowed is inflated by VOLUME a lead creates (trailing offenses throw more);
            # yards/attempt strips that volume out and measures the pass defense itself.
            "pass_att_allowed": float(opp["attempts"].sum()),
            "pass_ya_allowed": round(opp["passing_yards"].sum() / opp["attempts"].sum(), 2) if opp["attempts"].sum() else 0.0,
            "rush_td_allowed": float(opp["rushing_tds"].sum()),
            "pass_td_allowed": float(opp["passing_tds"].sum()),
            # offense: what T does
            "rush_ypg": round(own["rushing_yards"].sum() / gms, 1),
            "pass_ypg": round(own["passing_yards"].sum() / gms, 1),
            "rush_ypc": round(own["rushing_yards"].sum() / car_o, 2) if car_o else 0.0,
            "pass_ya": round(own["passing_yards"].sum() / own["attempts"].sum(), 2) if own["attempts"].sum() else 0.0,
            "sacks_allowed": float(own["sacks_suffered"].sum()),
            # turnovers: takeaways (defense forces) vs giveaways (offense loses)
            "takeaways": float(own["def_interceptions"].sum() + own["fumble_recovery_opp"].sum()),
            "giveaways": float(own["passing_interceptions"].sum() + own["rushing_fumbles_lost"].sum()
                               + own["receiving_fumbles_lost"].sum() + own["sack_fumbles_lost"].sum()),
        }
        rec[T]["to_margin"] = round(rec[T]["takeaways"] - rec[T]["giveaways"], 1)

    # --- Strength-of-schedule adjustment ---------------------------------------
    # A raw rank is flattered by an easy slate: ATL's #1 run D faced PIT + CAR. So
    # discount each defense's yards allowed by the quality of the OFFENSES it faced,
    # measured by what those offenses did in their OTHER games (head-to-head excluded
    # so the number isn't circular). Faced weak offenses -> adjust allowed up; faced
    # strong ones -> adjust down. Single-pass SoS, not a full iterative rating.
    league_off_rush = sum(rec[t]["rush_ypg"] for t in rec) / len(rec)
    league_off_pass = sum(rec[t]["pass_ypg"] for t in rec) / len(rec)
    # per-play league baselines (for the per-dropback / per-carry SoS adjustment)
    league_off_pass_ya = sum(rec[t]["pass_ya"] for t in rec) / len(rec)
    league_off_rush_ypc = sum(rec[t]["rush_ypc"] for t in rec) / len(rec)

    def _opp_off(team, exclude, col):
        """Opponent `team`'s offensive yds/game in `col`, excluding games vs `exclude`."""
        g = df[(df["team"] == team) & (df["opponent_team"] != exclude)]
        n = g["week"].nunique()
        if not n:
            return league_off_rush if "rush" in col else league_off_pass
        return g[col].sum() / n

    def _opp_off_rate(team, exclude, num_col, den_col, fallback):
        """Opponent `team`'s offensive RATE (num/den), excluding games vs `exclude`."""
        g = df[(df["team"] == team) & (df["opponent_team"] != exclude)]
        den = g[den_col].sum()
        if not den:
            return fallback
        return g[num_col].sum() / den

    for T in rec:
        faced = rec[T]["opps_faced"] or []
        if faced:
            fr = sum(_opp_off(o, T, "rushing_yards") for o in faced) / len(faced)
            fp = sum(_opp_off(o, T, "passing_yards") for o in faced) / len(faced)
        else:
            fr, fp = league_off_rush, league_off_pass
        rec[T]["faced_off_rush"] = round(fr, 1)
        rec[T]["faced_off_pass"] = round(fp, 1)
        rec[T]["sos_rush"] = round(league_off_rush - fr, 1)   # +ve => faced weak rush offenses
        rec[T]["sos_pass"] = round(league_off_pass - fp, 1)
        rec[T]["rush_ypg_allowed_adj"] = round(rec[T]["rush_ypg_allowed"] + rec[T]["sos_rush"], 1)
        rec[T]["pass_ypg_allowed_adj"] = round(rec[T]["pass_ypg_allowed"] + rec[T]["sos_pass"], 1)
        # per-play (per-dropback / per-carry) SoS adjustment -- same logic, rate basis
        if faced:
            fp_ya = sum(_opp_off_rate(o, T, "passing_yards", "attempts", league_off_pass_ya) for o in faced) / len(faced)
            fr_ypc = sum(_opp_off_rate(o, T, "rushing_yards", "carries", league_off_rush_ypc) for o in faced) / len(faced)
        else:
            fp_ya, fr_ypc = league_off_pass_ya, league_off_rush_ypc
        rec[T]["sos_pass_ya"] = round(league_off_pass_ya - fp_ya, 2)
        rec[T]["sos_rush_ypc"] = round(league_off_rush_ypc - fr_ypc, 2)
        rec[T]["pass_ya_allowed_adj"] = round(rec[T]["pass_ya_allowed"] + rec[T]["sos_pass_ya"], 2)
        rec[T]["rush_ypc_allowed_adj"] = round(rec[T]["rush_ypc_allowed"] + rec[T]["sos_rush_ypc"], 2)
        # combined schedule strength (avg of the two offensive sides faced), for a label
        strength = ((fr - league_off_rush) + (fp - league_off_pass)) / 2  # +ve => tough slate
        rec[T]["sos_pts"] = round(strength, 1)

    # league ranks (1 = best defense) on the metrics a game read turns on
    frame = pd.DataFrame(rec).T
    rank_specs = [
        ("def_sacks", False, "sack_rank"),
        ("def_qb_hits", False, "qbhit_rank"),
        ("rush_ypc_allowed", True, "rush_ypc_rank"),
        ("rush_ypg_allowed", True, "rush_ypg_rank"),
        ("pass_ypg_allowed", True, "pass_ypg_rank"),
        ("rush_ypg_allowed_adj", True, "rush_ypg_adj_rank"),
        ("pass_ypg_allowed_adj", True, "pass_ypg_adj_rank"),
        # per-play (A2): rank the defense by efficiency allowed, not volume allowed
        ("pass_ya_allowed", True, "pass_ya_rank"),
        ("pass_ya_allowed_adj", True, "pass_ya_adj_rank"),
        ("rush_ypc_allowed_adj", True, "rush_ypc_adj_rank"),
        ("sos_pts", False, "sos_rank"),  # 1 = toughest schedule faced
        # offense (1 = most yards) + turnovers (1 = best: most takeaways / fewest
        # giveaways / best margin) + pass protection (1 = fewest sacks allowed)
        ("rush_ypg", False, "off_rush_rank"),
        ("pass_ypg", False, "off_pass_rank"),
        ("sacks_allowed", True, "sacks_allowed_rank"),
        ("takeaways", False, "takeaway_rank"),
        ("giveaways", True, "giveaway_rank"),
        ("to_margin", False, "to_margin_rank"),
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
