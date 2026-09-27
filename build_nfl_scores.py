#!/usr/bin/env python3
"""
Build the inputs for the NFL totals model: team scoring (prior + current) and QB1.

The totals model needs (a) last season's per-team offense/defense scoring as a stable
prior, (b) this season's game-by-game scores to opponent-adjust, and (c) each team's
STARTING QB, so a QB-out injury can veto the projection (a scoring model is otherwise
blind to its starter being done -- Jaxson Dart out for the year, Jayden Daniels out).

Sources: nflverse games.csv (scores) + stats_player_week (leading passer per team).
Output: data/scenarios/nfl_scores.json  { prior_season, season, league_pts, prior:{team:[off,def]},
                                           games:[[home,away,hs,as]], qb1:{team:{name,att}} }
"""
from __future__ import annotations
import csv
import io
import json
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUT_PATH = BASE_DIR / "data" / "scenarios" / "nfl_scores.json"
GAMES_URL = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"
STATS_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.parquet"
UA = {"User-Agent": "Mozilla/5.0"}
TEAM_NORM = {"LA": "LAR"}


def _norm(t):
    return TEAM_NORM.get(t, t)


def _games(rows, season):
    out = []
    for r in rows:
        if r.get("season") == str(season) and r.get("game_type") == "REG" \
                and r.get("home_score") not in (None, "", "NA"):
            out.append([_norm(r["home_team"]), _norm(r["away_team"]),
                        int(r["home_score"]), int(r["away_score"])])
    return out


def _skill_leaders(season):
    """Per team: leading passer (QB1), receiver (WR1, by rec yds) and rusher (RB1, by
    carries), so QB/WR1/RB1 injuries can be weighted. From nflverse weekly stats."""
    try:
        import pandas as pd
        tmp = BASE_DIR / "data" / "scenarios" / f"_nflqb_{season}.parquet"
        urllib.request.urlretrieve(STATS_URL.format(season=season), tmp)
        df = pd.read_parquet(tmp)
        tmp.unlink(missing_ok=True)
        for c in ("attempts", "receiving_yards", "receptions", "carries", "rushing_yards"):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

        def _qb(team_df):
            g = df[df["attempts"] > 0].groupby(["team", "player_display_name"]).agg(
                v=("attempts", "sum")).reset_index()
            out = {}
            for team, grp in g.groupby("team"):
                t = grp.sort_values("v", ascending=False).iloc[0]
                out[_norm(team)] = {"name": str(t["player_display_name"]), "att": int(t["v"])}
            return out

        def _corps(mask_col, val_col, topn):
            """Per team: [[name, production], ...] for the top contributors -- so an
            injury can be weighted by the SHARE of production that's out, not just #1."""
            g = df[df[mask_col] > 0].groupby(["team", "player_display_name"]).agg(
                v=(val_col, "sum")).reset_index()
            out = {}
            for team, grp in g.groupby("team"):
                top = grp.sort_values("v", ascending=False).head(topn)
                out[_norm(team)] = [[str(r.player_display_name), int(r.v)] for r in top.itertuples()]
            return out
        return _qb(df), _corps("receptions", "receiving_yards", 8), _corps("carries", "carries", 4)
    except Exception as e:
        print(f"  skill leaders skipped: {e}")
        return {}, {}, {}


def build(season: int, prior_season: int) -> dict:
    rows = list(csv.DictReader(io.StringIO(
        urllib.request.urlopen(urllib.request.Request(GAMES_URL, headers=UA), timeout=60).read().decode())))
    g_prior = _games(rows, prior_season)
    g_now = _games(rows, season)
    poff, pdef = defaultdict(list), defaultdict(list)
    for h, a, hs, as_ in g_prior:
        poff[h].append(hs); pdef[h].append(as_); poff[a].append(as_); pdef[a].append(hs)
    prior = {t: [round(sum(poff[t]) / len(poff[t]), 2), round(sum(pdef[t]) / len(pdef[t]), 2)] for t in poff}
    allpts = [hs for _, _, hs, _ in g_now] + [as_ for _, _, _, as_ in g_now]
    lp = round(sum(allpts) / len(allpts), 2) if allpts else 22.5
    qb1, recv, rush = _skill_leaders(season)
    return {
        "season": season, "prior_season": prior_season,
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "league_pts": lp, "prior": prior, "games": g_now,
        "qb1": qb1, "recv": recv, "rush": rush,
    }


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--prior-season", type=int, default=2025)
    args = ap.parse_args()
    data = build(args.season, args.prior_season)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Wrote {len(data['games'])} {args.season} games, {len(data['prior'])} prior ratings, "
          f"{len(data['qb1'])} QB1s -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
