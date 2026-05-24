from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import time

import pandas as pd
from nba_api.stats.library.http import NBAStatsHTTP


BASE_DIR = Path(__file__).resolve().parent
TRACKING_DIR = BASE_DIR / "data" / "tracking"
TRACKING_DIR.mkdir(parents=True, exist_ok=True)


def detect_season() -> str:
    now = datetime.now()
    if now.month >= 10:
        return f"{now.year}-{str(now.year + 1)[2:]}"
    return f"{now.year - 1}-{str(now.year)[2:]}"


def fetch_measure(season: str, measure: str) -> pd.DataFrame:
    params = {
        "LastNGames": "0",
        "Month": "0",
        "OpponentTeamID": 0,
        "PerMode": "PerGame",
        "PlayerOrTeam": "Player",
        "PtMeasureType": measure,
        "Season": season,
        "SeasonType": "Regular Season",
        "College": "",
        "Conference": "",
        "Country": "",
        "DateFrom": "",
        "DateTo": "",
        "Division": "",
        "DraftPick": "",
        "DraftYear": "",
        "GameScope": "",
        "Height": "",
        "LeagueID": "00",
        "Location": "",
        "Outcome": "",
        "PORound": "",
        "PlayerExperience": "",
        "PlayerPosition": "",
        "SeasonSegment": "",
        "StarterBench": "",
        "TeamID": "",
        "VsConference": "",
        "VsDivision": "",
        "Weight": "",
    }
    data = NBAStatsHTTP().send_api_request(endpoint="leaguedashptstats", parameters=params).get_dict()
    result = None
    if "resultSets" in data and data["resultSets"]:
        result = data["resultSets"][0]
    elif "resultSet" in data:
        result = data["resultSet"]
    if not result:
        raise RuntimeError(f"Unexpected response shape for {measure}: {list(data.keys())}")
    return pd.DataFrame(result["rowSet"], columns=result["headers"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh NBA player tracking stats (touches, drives, speed).")
    parser.add_argument("--season", default=detect_season(), help="Season like 2025-26")
    args = parser.parse_args()

    season = args.season
    print("=" * 60)
    print("BANKROLL KINGS - Refresh Tracking Stats")
    print("=" * 60)
    print(f"Season: {season}")

    speed_df = fetch_measure(season, "SpeedDistance")
    time.sleep(0.7)
    touches_df = fetch_measure(season, "ElbowTouch")
    time.sleep(0.7)
    drives_df = fetch_measure(season, "Drives")

    speed_path = TRACKING_DIR / "NBA_Tracking.csv"
    speed_df.to_csv(speed_path, index=False)

    player_tracking = speed_df[["PLAYER_NAME", "AVG_SPEED", "DIST_MILES"]].copy()
    player_tracking.rename(columns={"PLAYER_NAME": "Player"}, inplace=True)

    if "PLAYER_NAME" in touches_df.columns and "TOUCHES" in touches_df.columns:
        touches_subset = touches_df[["PLAYER_NAME", "TOUCHES"]].copy()
        touches_subset.rename(columns={"PLAYER_NAME": "Player"}, inplace=True)
        player_tracking = player_tracking.merge(touches_subset, on="Player", how="outer")

    if "PLAYER_NAME" in drives_df.columns and "DRIVES" in drives_df.columns:
        drives_subset = drives_df[["PLAYER_NAME", "DRIVES"]].copy()
        drives_subset.rename(columns={"PLAYER_NAME": "Player"}, inplace=True)
        player_tracking = player_tracking.merge(drives_subset, on="Player", how="outer")

    player_tracking = player_tracking.sort_values("Player").drop_duplicates(subset=["Player"], keep="last")
    player_tracking_path = TRACKING_DIR / "NBA_PlayerTracking.csv"
    player_tracking.to_csv(player_tracking_path, index=False)

    print(f"Saved speed-distance file: {speed_path}")
    print(f"Saved merged player tracking file: {player_tracking_path}")
    print(f"Rows: {len(player_tracking)}")
    print(f"Columns: {list(player_tracking.columns)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
