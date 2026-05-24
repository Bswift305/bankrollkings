from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
HISTORICAL_DIR = BASE_DIR / "data" / "historical"
DEFAULT_OUTPUT = HISTORICAL_DIR / "NFL_PlayerStats_2025.csv"
DEFAULT_GAMES_OUTPUT = HISTORICAL_DIR / "NFL_Games_2025_from_pbp.csv"


PBP_COLUMNS = [
    "game_id",
    "season",
    "week",
    "season_type",
    "game_date",
    "home_team",
    "away_team",
    "home_score",
    "away_score",
    "posteam",
    "defteam",
    "pass_attempt",
    "complete_pass",
    "pass_touchdown",
    "interception",
    "passing_yards",
    "passer_player_id",
    "passer_player_name",
    "rush_attempt",
    "rush_touchdown",
    "rushing_yards",
    "rusher_player_id",
    "rusher_player_name",
    "receiving_yards",
    "receiver_player_id",
    "receiver_player_name",
    "touchdown",
    "td_player_name",
    "target_share",
    "air_yards",
    "yards_after_catch",
    "spread_line",
    "total_line",
    "div_game",
    "roof",
    "surface",
    "temp",
    "wind",
    "location",
    "result",
    "total",
    "home_coach",
    "away_coach",
    "stadium_id",
    "game_stadium",
]


def read_pbp(path: Path) -> pd.DataFrame:
    available = pd.read_csv(path, nrows=0, low_memory=False).columns.tolist()
    usecols = [col for col in PBP_COLUMNS if col in available]
    df = pd.read_csv(path, usecols=usecols, low_memory=False)
    for column in ["season", "week"]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    for column in [
        "pass_attempt",
        "complete_pass",
        "pass_touchdown",
        "interception",
        "passing_yards",
        "rush_attempt",
        "rush_touchdown",
        "rushing_yards",
        "receiving_yards",
        "air_yards",
        "yards_after_catch",
    ]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0)
    return df


def empty_stat_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "player_id",
        "player_display_name",
        "season",
        "week",
        "season_type",
        "team",
        "opponent_team",
        "completions",
        "attempts",
        "passing_yards",
        "passing_tds",
        "passing_interceptions",
        "carries",
        "rushing_yards",
        "rushing_tds",
        "receptions",
        "targets",
        "receiving_yards",
        "receiving_tds",
        "receiving_air_yards",
        "receiving_yards_after_catch",
    ])


def aggregate_passing(pbp: pd.DataFrame) -> pd.DataFrame:
    needed = {"passer_player_name", "posteam", "defteam", "pass_attempt"}
    if not needed <= set(pbp.columns):
        return empty_stat_frame()
    rows = pbp[
        (pbp["passer_player_name"].fillna("").astype(str).str.strip() != "")
        & (pd.to_numeric(pbp["pass_attempt"], errors="coerce").fillna(0) == 1)
    ].copy()
    if rows.empty:
        return empty_stat_frame()
    grouped = rows.groupby([
        "game_id", "season", "week", "season_type", "passer_player_id",
        "passer_player_name", "posteam", "defteam"
    ], dropna=False).agg(
        completions=("complete_pass", "sum"),
        attempts=("pass_attempt", "sum"),
        passing_yards=("passing_yards", "sum"),
        passing_tds=("pass_touchdown", "sum"),
        passing_interceptions=("interception", "sum"),
    ).reset_index()
    return grouped.rename(columns={
        "passer_player_id": "player_id",
        "passer_player_name": "player_display_name",
        "posteam": "team",
        "defteam": "opponent_team",
    })


def aggregate_rushing(pbp: pd.DataFrame) -> pd.DataFrame:
    needed = {"rusher_player_name", "posteam", "defteam", "rush_attempt"}
    if not needed <= set(pbp.columns):
        return empty_stat_frame()
    rows = pbp[
        (pbp["rusher_player_name"].fillna("").astype(str).str.strip() != "")
        & (pd.to_numeric(pbp["rush_attempt"], errors="coerce").fillna(0) == 1)
    ].copy()
    if rows.empty:
        return empty_stat_frame()
    grouped = rows.groupby([
        "game_id", "season", "week", "season_type", "rusher_player_id",
        "rusher_player_name", "posteam", "defteam"
    ], dropna=False).agg(
        carries=("rush_attempt", "sum"),
        rushing_yards=("rushing_yards", "sum"),
        rushing_tds=("rush_touchdown", "sum"),
    ).reset_index()
    return grouped.rename(columns={
        "rusher_player_id": "player_id",
        "rusher_player_name": "player_display_name",
        "posteam": "team",
        "defteam": "opponent_team",
    })


def aggregate_receiving(pbp: pd.DataFrame) -> pd.DataFrame:
    needed = {"receiver_player_name", "posteam", "defteam", "pass_attempt"}
    if not needed <= set(pbp.columns):
        return empty_stat_frame()
    rows = pbp[pbp["receiver_player_name"].fillna("").astype(str).str.strip() != ""].copy()
    rows = rows[pd.to_numeric(rows.get("pass_attempt"), errors="coerce").fillna(0) == 1].copy()
    if rows.empty:
        return empty_stat_frame()
    if "td_player_name" not in rows.columns:
        rows["td_player_name"] = ""
    rows["receiving_td_flag"] = (
        (pd.to_numeric(rows.get("pass_touchdown"), errors="coerce").fillna(0) == 1)
        & (rows["td_player_name"].fillna("").astype(str) == rows["receiver_player_name"].fillna("").astype(str))
    ).astype(int)
    grouped = rows.groupby([
        "game_id", "season", "week", "season_type", "receiver_player_id",
        "receiver_player_name", "posteam", "defteam"
    ], dropna=False).agg(
        receptions=("complete_pass", "sum"),
        targets=("pass_attempt", "sum"),
        receiving_yards=("receiving_yards", "sum"),
        receiving_tds=("receiving_td_flag", "sum"),
        receiving_air_yards=("air_yards", "sum"),
        receiving_yards_after_catch=("yards_after_catch", "sum"),
    ).reset_index()
    return grouped.rename(columns={
        "receiver_player_id": "player_id",
        "receiver_player_name": "player_display_name",
        "posteam": "team",
        "defteam": "opponent_team",
    })


def combine_player_stats(passing: pd.DataFrame, rushing: pd.DataFrame, receiving: pd.DataFrame) -> pd.DataFrame:
    key_cols = [
        "game_id", "season", "week", "season_type", "player_id",
        "player_display_name", "team", "opponent_team"
    ]
    frames = []
    for frame in [passing, rushing, receiving]:
        if frame is not None and not frame.empty:
            frames.append(frame)
    if not frames:
        return empty_stat_frame()
    combined = frames[0]
    for frame in frames[1:]:
        combined = combined.merge(frame, on=key_cols, how="outer")
    numeric_cols = [
        "completions", "attempts", "passing_yards", "passing_tds", "passing_interceptions",
        "carries", "rushing_yards", "rushing_tds",
        "receptions", "targets", "receiving_yards", "receiving_tds",
        "receiving_air_yards", "receiving_yards_after_catch",
    ]
    for col in numeric_cols:
        if col not in combined.columns:
            combined[col] = 0
        combined[col] = pd.to_numeric(combined[col], errors="coerce").fillna(0)
    combined["player_name"] = combined["player_display_name"]
    combined["position"] = ""
    combined["position_group"] = ""
    combined["headshot_url"] = ""
    combined["target_share"] = combined["targets"] / combined.groupby(["game_id", "team"])["targets"].transform("sum").replace(0, pd.NA)
    combined["air_yards_share"] = combined["receiving_air_yards"] / combined.groupby(["game_id", "team"])["receiving_air_yards"].transform("sum").replace(0, pd.NA)
    combined["fantasy_points"] = (
        combined["passing_yards"] * 0.04
        + combined["passing_tds"] * 4
        - combined["passing_interceptions"] * 2
        + combined["rushing_yards"] * 0.1
        + combined["rushing_tds"] * 6
        + combined["receiving_yards"] * 0.1
        + combined["receiving_tds"] * 6
    )
    combined["fantasy_points_ppr"] = combined["fantasy_points"] + combined["receptions"]
    ordered = [
        "player_id", "player_name", "player_display_name", "position", "position_group", "headshot_url",
        "season", "week", "season_type", "team", "opponent_team",
        "completions", "attempts", "passing_yards", "passing_tds", "passing_interceptions",
        "carries", "rushing_yards", "rushing_tds",
        "receptions", "targets", "receiving_yards", "receiving_tds",
        "receiving_air_yards", "receiving_yards_after_catch", "target_share", "air_yards_share",
        "fantasy_points", "fantasy_points_ppr",
    ]
    return combined[ordered].sort_values(["season", "week", "team", "player_display_name"]).reset_index(drop=True)


def build_games_from_pbp(pbp: pd.DataFrame) -> pd.DataFrame:
    game_cols = [
        "game_id", "season", "season_type", "week", "game_date", "away_team", "away_score",
        "home_team", "home_score", "location", "result", "total", "spread_line", "total_line",
        "div_game", "roof", "surface", "temp", "wind", "away_coach", "home_coach",
        "stadium_id", "game_stadium",
    ]
    available = [col for col in game_cols if col in pbp.columns]
    if not available:
        return pd.DataFrame()
    games = pbp[available].drop_duplicates(subset=["game_id"], keep="last").copy()
    rename = {"game_date": "gameday", "game_stadium": "stadium"}
    games = games.rename(columns={k: v for k, v in rename.items() if k in games.columns})
    if "game_type" not in games.columns and "season_type" in games.columns:
        games["game_type"] = games["season_type"]
    return games.sort_values(["season", "week", "game_id"]).reset_index(drop=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate nflverse play-by-play into NFL player game stats.")
    parser.add_argument("pbp_csv", help="Input play-by-play CSV.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output player stats CSV.")
    parser.add_argument("--games-output", default=str(DEFAULT_GAMES_OUTPUT), help="Output game context CSV.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pbp = read_pbp(Path(args.pbp_csv))
    passing = aggregate_passing(pbp)
    rushing = aggregate_rushing(pbp)
    receiving = aggregate_receiving(pbp)
    stats = combine_player_stats(passing, rushing, receiving)
    games = build_games_from_pbp(pbp)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    stats.to_csv(output, index=False)

    games_output = Path(args.games_output)
    games_output.parent.mkdir(parents=True, exist_ok=True)
    games.to_csv(games_output, index=False)

    print(f"Player game rows: {len(stats):,}")
    print(f"Games: {len(games):,}")
    print(f"Saved player stats: {output}")
    print(f"Saved game context: {games_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
