from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
from nba_api.stats.endpoints import leaguegamefinder


BASE_DIR = Path(__file__).resolve().parent
GAMELOG_DIR = BASE_DIR / "data" / "gamelogs"
GAMELOG_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_PATH = GAMELOG_DIR / "WNBA_GameLogs.csv"
LEAGUE_ID_WNBA = "10"


def infer_season_string(today: datetime | None = None) -> str:
    now = today or datetime.now()
    return str(now.year)


def normalize_wnba_gamelogs(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    df = df.copy()
    rename_map = {
        "PLAYER_NAME": "Player",
        "PLAYER_ID": "PlayerID",
        "GAME_DATE": "Date",
        "MATCHUP": "Matchup",
        "WL": "Result",
        "TEAM_ABBREVIATION": "Team",
        "FG3M": "3PM",
    }
    df = df.rename(columns=rename_map)

    keep_cols = [
        "SEASON_ID",
        "Player",
        "PlayerID",
        "GAME_ID",
        "Date",
        "Matchup",
        "Result",
        "MIN",
        "FGM",
        "FGA",
        "FG_PCT",
        "3PM",
        "FG3A",
        "FG3_PCT",
        "FTM",
        "FTA",
        "FT_PCT",
        "OREB",
        "DREB",
        "REB",
        "AST",
        "STL",
        "BLK",
        "TOV",
        "PF",
        "PTS",
        "PLUS_MINUS",
        "Team",
    ]
    existing = [col for col in keep_cols if col in df.columns]
    df = df[existing].copy()

    if "Matchup" in df.columns:
        def infer_opp(matchup: str) -> str:
            parts = str(matchup).split()
            return parts[-1] if parts else ""

        df["Opp"] = df["Matchup"].map(infer_opp)

    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.strftime("%Y-%m-%d")

    return df


def main() -> int:
    season = infer_season_string()
    print("=" * 60)
    print("BANKROLL KINGS - Refresh WNBA Player Logs")
    print("=" * 60)
    print(f"Season: {season}")

    try:
        finder = leaguegamefinder.LeagueGameFinder(
            player_or_team_abbreviation="P",
            league_id_nullable=LEAGUE_ID_WNBA,
            season_nullable=season,
            season_type_nullable="Regular Season",
        )
        frames = finder.get_data_frames()
        raw = frames[0] if frames else pd.DataFrame()
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    final_df = normalize_wnba_gamelogs(raw)
    if final_df.empty:
        print("No WNBA player logs returned.")
        pd.DataFrame().to_csv(OUTPUT_PATH, index=False)
        return 0

    final_df.to_csv(OUTPUT_PATH, index=False)
    print(f"Saved {len(final_df)} WNBA player logs to {OUTPUT_PATH}")
    print(f"Players: {final_df['Player'].nunique() if 'Player' in final_df.columns else 0}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
