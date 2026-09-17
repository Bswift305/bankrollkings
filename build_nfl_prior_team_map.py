#!/usr/bin/env python3
"""
Build the prior-season team map used by the early-season usage gate.

For each player, records the team they played the MOST games for last season
(mode, not last-game, so a one-game blip doesn't mislabel a stable starter).
The gate compares this to the current roster to find players who changed teams,
whose usage/volume PropScore projections are unreliable in the first few weeks
(no current-season snaps/targets/carries yet).

Source: nflverse weekly player stats (canonical, free). Run preseason / when
rosters settle. Output: data/rosters/NFL_PriorSeasonTeams.csv
"""
from __future__ import annotations
import argparse
import urllib.request
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
OUT_PATH = BASE_DIR / "data" / "rosters" / "NFL_PriorSeasonTeams.csv"
STATS_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.parquet"


def build(prior_season: int) -> pd.DataFrame:
    url = STATS_URL.format(season=prior_season)
    tmp = BASE_DIR / "data" / "rosters" / f"_stats_{prior_season}.parquet"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    print(f"Fetching {url}")
    urllib.request.urlretrieve(url, tmp)
    df = pd.read_parquet(tmp).dropna(subset=["player_display_name", "team"])
    # nflverse team codes -> current-roster (ESPN) codes. Only the Rams differ today
    # (nflverse 'LA' vs roster 'LAR'); the rest align. Extra aliases are defensive.
    TEAM_NORM = {"LA": "LAR", "LARM": "LAR", "WSH": "WAS", "JAC": "JAX", "LVR": "LV"}
    df["team"] = df["team"].replace(TEAM_NORM)
    # team the player logged the most games for last season
    counts = (df.groupby(["player_display_name", "team"]).size()
                .reset_index(name="games").sort_values("games", ascending=False))
    prior = counts.drop_duplicates("player_display_name", keep="first")
    out = prior.rename(columns={"player_display_name": "Player", "team": "PriorTeam"})[["Player", "PriorTeam", "games"]]
    out["PriorSeason"] = prior_season
    return out.reset_index(drop=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prior-season", type=int, default=2025)
    args = ap.parse_args()
    out = build(args.prior_season)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_PATH, index=False)
    print(f"Wrote {len(out)} players -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
