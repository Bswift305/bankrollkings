"""
Bankroll Kings - Prop Importer
==============================

Normalize pasted/exported sportsbook prop sheets into data/props/NBA_Props.csv.

Examples:
    py import_props.py --input raw_props.csv
    py import_props.py --input draftkings.xlsx --sheet Props
    py import_props.py --input raw_props.csv --output data/props/NBA_Props.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd


BASE_DIR = Path(__file__).parent.resolve()
DEFAULT_OUTPUT = BASE_DIR / "data" / "props" / "NBA_Props.csv"

OUTPUT_COLUMNS = [
    "Player",
    "Team",
    "Stat",
    "Line",
    "Game",
    "Book",
    "LastUpdated",
    "OpenLine",
    "CurrentLine",
    "CloseLine",
    "OpenOverOdds",
    "OpenUnderOdds",
    "OverOdds",
    "UnderOdds",
    "CloseOverOdds",
    "CloseUnderOdds",
    "BetLine",
    "BetOverOdds",
    "BetUnderOdds",
    "BetBook",
    "BetTime",
]

TEAM_NAME_TO_ABBREV = {
    "ATLANTA HAWKS": "ATL",
    "BOSTON CELTICS": "BOS",
    "BROOKLYN NETS": "BKN",
    "CHARLOTTE HORNETS": "CHA",
    "CHICAGO BULLS": "CHI",
    "CLEVELAND CAVALIERS": "CLE",
    "DALLAS MAVERICKS": "DAL",
    "DENVER NUGGETS": "DEN",
    "DETROIT PISTONS": "DET",
    "GOLDEN STATE WARRIORS": "GSW",
    "HOUSTON ROCKETS": "HOU",
    "INDIANA PACERS": "IND",
    "LOS ANGELES CLIPPERS": "LAC",
    "LA CLIPPERS": "LAC",
    "LOS ANGELES LAKERS": "LAL",
    "MEMPHIS GRIZZLIES": "MEM",
    "MIAMI HEAT": "MIA",
    "MILWAUKEE BUCKS": "MIL",
    "MINNESOTA TIMBERWOLVES": "MIN",
    "NEW ORLEANS PELICANS": "NOP",
    "NEW YORK KNICKS": "NYK",
    "OKLAHOMA CITY THUNDER": "OKC",
    "ORLANDO MAGIC": "ORL",
    "PHILADELPHIA 76ERS": "PHI",
    "PHOENIX SUNS": "PHX",
    "PORTLAND TRAIL BLAZERS": "POR",
    "SACRAMENTO KINGS": "SAC",
    "SAN ANTONIO SPURS": "SAS",
    "TORONTO RAPTORS": "TOR",
    "UTAH JAZZ": "UTA",
    "WASHINGTON WIZARDS": "WAS",
}

STAT_ALIASES = {
    "POINTS": "PTS",
    "PTS": "PTS",
    "POINTS SCORED": "PTS",
    "REBOUNDS": "REB",
    "REB": "REB",
    "ASSISTS": "AST",
    "AST": "AST",
    "3-POINTERS MADE": "3PM",
    "THREES": "3PM",
    "THREE POINTERS MADE": "3PM",
    "3PM": "3PM",
    "3PTS": "3PM",
    "STEALS": "STL",
    "STL": "STL",
    "BLOCKS": "BLK",
    "BLK": "BLK",
}


def normalize_key(value: str) -> str:
    return "".join(ch.lower() for ch in str(value) if ch.isalnum())


COLUMN_ALIASES = {
    "player": "Player",
    "name": "Player",
    "description": "Player",
    "team": "Team",
    "teamabbr": "Team",
    "teamabbreviation": "Team",
    "stat": "Stat",
    "market": "Stat",
    "marketname": "Stat",
    "prop": "Stat",
    "line": "Line",
    "points": "Line",
    "currentline": "CurrentLine",
    "openingline": "OpenLine",
    "openline": "OpenLine",
    "closeline": "CloseLine",
    "gameline": "CurrentLine",
    "game": "Game",
    "matchup": "Game",
    "event": "Game",
    "book": "Book",
    "sportsbook": "Book",
    "lastupdated": "LastUpdated",
    "updated": "LastUpdated",
    "time": "LastUpdated",
    "openoverodds": "OpenOverOdds",
    "openunderodds": "OpenUnderOdds",
    "overodds": "OverOdds",
    "underodds": "UnderOdds",
    "closeoverodds": "CloseOverOdds",
    "closeunderodds": "CloseUnderOdds",
    "betline": "BetLine",
    "betoverodds": "BetOverOdds",
    "betunderodds": "BetUnderOdds",
    "betbook": "BetBook",
    "bettime": "BetTime",
    "side": "Direction",
    "direction": "Direction",
    "pick": "Direction",
    "selection": "Direction",
    "odds": "Odds",
    "price": "Odds",
    "americanodds": "Odds",
    "home": "Home",
    "away": "Away",
}


def rename_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {}
    for column in df.columns:
        key = normalize_key(column)
        if key in COLUMN_ALIASES:
            rename_map[column] = COLUMN_ALIASES[key]
    return df.rename(columns=rename_map).copy()


def clean_team(value) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if len(text) == 3:
        return text.upper()
    return TEAM_NAME_TO_ABBREV.get(text.upper(), text.upper())


def clean_stat(value) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip().upper()
    return STAT_ALIASES.get(text, text)


def clean_direction(value) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip().upper()
    if "OVER" in text:
        return "OVER"
    if "UNDER" in text:
        return "UNDER"
    return text


def build_game_column(df: pd.DataFrame) -> pd.Series:
    if "Game" in df.columns:
        return df["Game"].fillna("").astype(str).str.strip()
    if "Away" in df.columns and "Home" in df.columns:
        away = df["Away"].map(clean_team)
        home = df["Home"].map(clean_team)
        return away + "@" + home
    return pd.Series([""] * len(df))


def pivot_directional_odds(df: pd.DataFrame) -> pd.DataFrame:
    if "Direction" not in df.columns or "Odds" not in df.columns:
        return df

    df = df.copy()
    df["Direction"] = df["Direction"].map(clean_direction)

    id_columns = [col for col in df.columns if col not in {"Direction", "Odds"}]
    grouped_rows = []
    for _, group in df.groupby(id_columns, dropna=False):
        row = group.iloc[0].to_dict()
        row.pop("Direction", None)
        row.pop("Odds", None)
        for _, item in group.iterrows():
            direction = item.get("Direction", "")
            odds_value = item.get("Odds")
            if direction == "OVER":
                row["OverOdds"] = odds_value
            elif direction == "UNDER":
                row["UnderOdds"] = odds_value
        grouped_rows.append(row)

    return pd.DataFrame(grouped_rows)


def ensure_market_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for column in OUTPUT_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA

    if "CurrentLine" not in df.columns or df["CurrentLine"].isna().all():
        df["CurrentLine"] = df["Line"]
    if "Line" not in df.columns or df["Line"].isna().all():
        df["Line"] = df["CurrentLine"]

    numeric_columns = [
        "Line",
        "OpenLine",
        "CurrentLine",
        "CloseLine",
        "OpenOverOdds",
        "OpenUnderOdds",
        "OverOdds",
        "UnderOdds",
        "CloseOverOdds",
        "CloseUnderOdds",
        "BetLine",
        "BetOverOdds",
        "BetUnderOdds",
    ]
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    return df[OUTPUT_COLUMNS]


def normalize_props(df: pd.DataFrame) -> pd.DataFrame:
    df = rename_columns(df)
    df = pivot_directional_odds(df)

    if "Player" not in df.columns or "Stat" not in df.columns:
        raise ValueError("Input file must include player and stat columns.")

    if "Line" not in df.columns and "CurrentLine" not in df.columns:
        raise ValueError("Input file must include a prop line column.")

    df["Player"] = df["Player"].fillna("").astype(str).str.strip()
    if "Team" in df.columns:
        df["Team"] = df["Team"].map(clean_team)
    else:
        df["Team"] = pd.Series([""] * len(df))
    df["Stat"] = df["Stat"].map(clean_stat)
    df["Game"] = build_game_column(df)

    if "Book" in df.columns:
        df["Book"] = df["Book"].fillna("Manual").astype(str).str.strip()
    else:
        df["Book"] = "Manual"

    for column in ["LastUpdated", "BetBook", "BetTime"]:
        if column in df.columns:
            df[column] = df[column].fillna("").astype(str).str.strip()

    df = df[df["Player"] != ""].copy()
    df = df[df["Stat"].isin(["PTS", "REB", "AST", "3PM", "STL", "BLK"])]

    if "CurrentLine" not in df.columns and "Line" in df.columns:
        df["CurrentLine"] = df["Line"]
    if "Line" not in df.columns and "CurrentLine" in df.columns:
        df["Line"] = df["CurrentLine"]

    df = ensure_market_columns(df)
    df = df.sort_values(["Game", "Player", "Stat", "Line"]).reset_index(drop=True)
    df = df.drop_duplicates(subset=["Player", "Team", "Stat", "Line", "Game"], keep="last")
    return df


def read_input_file(path: Path, sheet_name: str | None = None) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path, sheet_name=sheet_name or 0)
    raise ValueError(f"Unsupported file type: {suffix}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize sportsbook props into NBA_Props.csv")
    parser.add_argument("--input", required=True, help="Path to raw CSV/XLS/XLSX prop export")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Destination CSV path")
    parser.add_argument("--sheet", help="Excel sheet name to load")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()

    if not input_path.exists():
        print(f"Input file not found: {input_path}")
        return 1

    try:
        raw = read_input_file(input_path, args.sheet)
        normalized = normalize_props(raw)
    except Exception as exc:
        print(f"Import failed: {exc}")
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    normalized.to_csv(output_path, index=False)

    print(f"Imported {len(normalized)} props")
    print(f"Saved to: {output_path}")
    print("Columns:")
    print(", ".join(normalized.columns))
    return 0


if __name__ == "__main__":
    sys.exit(main())
