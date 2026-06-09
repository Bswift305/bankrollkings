"""
Bankroll Kings - Fetch Game Lines from The Odds API
===================================================

Examples:
    $env:ODDS_API_KEY="your_key_here"; py fetch_game_lines.py
    py fetch_game_lines.py --sport basketball_nba --bookmakers draftkings,fanduel --days 5
    py fetch_game_lines.py --sport americanfootball_nfl --bookmakers draftkings,caesars,fanduel,betmgm --days 7
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd
from services.env_loader import load_local_env
from services.timeutils import to_eastern_datetime_str


BASE_DIR = Path(__file__).parent.resolve()
load_local_env(BASE_DIR)
SPORT_OUTPUTS = {
    "basketball_nba": {
        "odds": BASE_DIR / "data" / "odds" / "NBA_Odds.csv",
        "schedules": BASE_DIR / "data" / "schedules" / "NBA_Odds.csv",
        "schedule_alias": BASE_DIR / "data" / "schedules" / "NBA_Schedule.csv",
    },
    "basketball_wnba": {
        "odds": BASE_DIR / "data" / "odds" / "WNBA_Odds.csv",
        "schedules": BASE_DIR / "data" / "schedules" / "WNBA_Odds.csv",
        "schedule_alias": BASE_DIR / "data" / "schedules" / "WNBA_Schedule.csv",
    },
    "americanfootball_nfl": {
        "odds": BASE_DIR / "data" / "odds" / "NFL_Odds.csv",
        "schedules": BASE_DIR / "data" / "schedules" / "NFL_Odds.csv",
        "schedule_alias": BASE_DIR / "data" / "schedules" / "NFL_Schedule.csv",
    },
    "americanfootball_ncaaf": {
        "odds": BASE_DIR / "data" / "odds" / "NCAAF_Odds.csv",
        "schedules": BASE_DIR / "data" / "schedules" / "NCAAF_Odds.csv",
        "schedule_alias": BASE_DIR / "data" / "schedules" / "NCAAF_Schedule.csv",
    },
    "baseball_mlb": {
        "odds": BASE_DIR / "data" / "odds" / "MLB_Odds.csv",
        "schedules": BASE_DIR / "data" / "schedules" / "MLB_Odds.csv",
        "schedule_alias": BASE_DIR / "data" / "schedules" / "MLB_Schedule.csv",
    },
}
DEFAULT_SPORT = "basketball_nba"
DEFAULT_BOOKMAKERS = "draftkings"
DEFAULT_REGIONS = "us"
SPORT_DEFAULT_MARKETS = {
    "basketball_nba": ["h2h", "spreads", "totals"],
    "basketball_wnba": ["h2h", "spreads", "totals"],
    "americanfootball_nfl": ["h2h", "spreads", "totals"],
    "americanfootball_ncaaf": ["h2h", "spreads", "totals"],
    "baseball_mlb": ["h2h", "spreads", "totals"],
}
SPORT_TRACKING_PREFIX = {
    "basketball_nba": "NBA",
    "basketball_wnba": "WNBA",
    "americanfootball_nfl": "NFL",
    "americanfootball_ncaaf": "NCAAF",
    "baseball_mlb": "MLB",
}

BOOKMAKER_TITLES = {
    "draftkings": "DraftKings",
    "fanduel": "FanDuel",
    "betmgm": "BetMGM",
    "caesars": "Caesars",
}


def get_api_key(cli_value: str | None) -> str:
    api_key = cli_value or os.getenv("ODDS_API_KEY") or os.getenv("THE_ODDS_API_KEY")
    if not api_key:
        raise ValueError("Missing API key. Set ODDS_API_KEY or pass --api-key.")
    return api_key.strip()


def get_json(url: str) -> list | dict:
    with urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def build_url(path: str, **params) -> str:
    clean_params = {k: v for k, v in params.items() if v not in [None, ""]}
    return f"https://api.the-odds-api.com{path}?{urlencode(clean_params)}"


def to_iso_local(value: str | None) -> str:
    # Convert the API's UTC commence time to a fixed Eastern display string.
    # See services.timeutils for why a bare .astimezone() is unsafe here.
    return to_eastern_datetime_str(value)


def fetch_events(api_key: str, days: int, sport: str = DEFAULT_SPORT) -> list[dict]:
    now = datetime.now(timezone.utc)
    commence_from = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    commence_to = (now + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    url = build_url(
        f"/v4/sports/{sport}/events",
        apiKey=api_key,
        dateFormat="iso",
        commenceTimeFrom=commence_from,
    )
    events = get_json(url)

    filtered = []
    for event in events:
        commence_time = event.get("commence_time")
        if not commence_time:
            continue
        if commence_time <= commence_to:
            filtered.append(event)
    return filtered


def blank_row(event: dict, bookmaker_title: str) -> dict:
    commence_time = event.get("commence_time")
    local_time = to_iso_local(commence_time)
    game_dt = ""
    game_time = ""
    if local_time:
        parts = local_time.split(" ", 1)
        game_dt = parts[0]
        game_time = parts[1] if len(parts) > 1 else ""

    return {
        "Date": game_dt,
        "Time": game_time,
        "Away": event.get("away_team", ""),
        "Home": event.get("home_team", ""),
        "AwayFull": event.get("away_team", ""),
        "HomeFull": event.get("home_team", ""),
        "AwayML": pd.NA,
        "HomeML": pd.NA,
        "Spread": pd.NA,
        "SpreadOdds": pd.NA,
        "Total": pd.NA,
        "OverOdds": pd.NA,
        "UnderOdds": pd.NA,
        "Book": bookmaker_title,
        "GameID": event.get("id", ""),
        "LastUpdated": "",
    }


def parse_event_markets(event: dict, bookmaker: dict) -> dict:
    bookmaker_title = bookmaker.get("title") or BOOKMAKER_TITLES.get(bookmaker.get("key", ""), bookmaker.get("key", ""))
    row = blank_row(event, bookmaker_title)
    row["LastUpdated"] = to_iso_local(bookmaker.get("last_update"))

    home = str(event.get("home_team", "")).strip()
    away = str(event.get("away_team", "")).strip()

    for market in bookmaker.get("markets", []):
        key = market.get("key")
        outcomes = market.get("outcomes", [])

        if key == "h2h":
            for outcome in outcomes:
                name = str(outcome.get("name", "")).strip()
                price = outcome.get("price")
                if name == home:
                    row["HomeML"] = price
                elif name == away:
                    row["AwayML"] = price

        elif key == "spreads":
            for outcome in outcomes:
                name = str(outcome.get("name", "")).strip()
                point = outcome.get("point")
                price = outcome.get("price")
                if name == home:
                    row["Spread"] = point
                    row["SpreadOdds"] = price
                    break
                if name == away and point not in [None, ""]:
                    row["Spread"] = -float(point)
                    row["SpreadOdds"] = price
                    break

        elif key == "totals":
            for outcome in outcomes:
                side = str(outcome.get("name", "")).strip().lower()
                point = outcome.get("point")
                price = outcome.get("price")
                if point not in [None, ""] and pd.isna(row["Total"]):
                    row["Total"] = point
                if side == "over":
                    row["OverOdds"] = price
                    if point not in [None, ""]:
                        row["Total"] = point
                elif side == "under":
                    row["UnderOdds"] = price
                    if point not in [None, ""] and pd.isna(row["Total"]):
                        row["Total"] = point

    return row


def fetch_odds_rows(api_key: str, sport: str, bookmakers: str, markets: list[str], regions: str, days: int) -> list[dict]:
    now = datetime.now(timezone.utc)
    commence_from = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    commence_to = (now + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    url = build_url(
        f"/v4/sports/{sport}/odds",
        apiKey=api_key,
        regions=regions,
        bookmakers=bookmakers,
        markets=",".join(markets),
        oddsFormat="american",
        dateFormat="iso",
        commenceTimeFrom=commence_from,
        commenceTimeTo=commence_to,
    )
    payload = get_json(url)
    rows = []
    for event in payload:
        for bookmaker in event.get("bookmakers", []):
            rows.append(parse_event_markets(event, bookmaker))
    return rows


def build_dataframe(rows: list[dict]) -> pd.DataFrame:
    columns = [
        "Date",
        "Time",
        "Away",
        "Home",
        "AwayFull",
        "HomeFull",
        "AwayML",
        "HomeML",
        "Spread",
        "SpreadOdds",
        "Total",
        "OverOdds",
        "UnderOdds",
        "Book",
        "GameID",
        "LastUpdated",
    ]

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=columns)

    for col in ["AwayML", "HomeML", "Spread", "SpreadOdds", "Total", "OverOdds", "UnderOdds"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df[columns]
    df = df.drop_duplicates(subset=["Date", "Away", "Home", "Book"], keep="last")
    return df.sort_values(["Date", "Time", "Away", "Home", "Book"]).reset_index(drop=True)


def build_schedule_alias(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["Date", "Time", "Away", "Home"])

    alias_columns = [
        "Date", "Time", "Away", "Home",
        "AwayFull", "HomeFull", "Book", "GameID", "LastUpdated"
    ]
    available = [col for col in alias_columns if col in df.columns]
    alias_df = df[available].copy()
    alias_df = alias_df.drop_duplicates(subset=[col for col in ["Date", "Away", "Home"] if col in alias_df.columns], keep="last")
    sort_cols = [col for col in ["Date", "Time", "Away", "Home"] if col in alias_df.columns]
    if sort_cols:
        alias_df = alias_df.sort_values(sort_cols).reset_index(drop=True)
    return alias_df


def append_line_movement_snapshot(df: pd.DataFrame, sport: str) -> None:
    if df is None or df.empty:
        return
    sport_prefix = SPORT_TRACKING_PREFIX.get(sport, sport.upper().replace("-", "_"))
    tracking_dir = BASE_DIR / "data" / "tracking"
    tracking_dir.mkdir(parents=True, exist_ok=True)
    history_path = tracking_dir / f"{sport_prefix}_LineMovementHistory.csv"
    current_path = tracking_dir / f"{sport_prefix}_LineMovementCurrent.csv"

    snapshot_at = datetime.now().astimezone().isoformat(timespec="seconds")
    snapshot = df.copy()
    snapshot.insert(0, "SnapshotAt", snapshot_at)
    snapshot.insert(1, "Sport", sport_prefix)

    if history_path.exists():
        try:
            history = pd.read_csv(history_path)
        except Exception:
            history = pd.DataFrame()
        history = pd.concat([history, snapshot], ignore_index=True, sort=False)
    else:
        history = snapshot

    dedupe_cols = [
        col for col in ["SnapshotAt", "Sport", "GameID", "Date", "Away", "Home", "Book"]
        if col in history.columns
    ]
    if dedupe_cols:
        history = history.drop_duplicates(subset=dedupe_cols, keep="last")
    history.to_csv(history_path, index=False)

    key_cols = [col for col in ["Sport", "GameID", "Date", "Away", "Home", "Book"] if col in history.columns]
    if not key_cols:
        return
    sort_cols = [col for col in ["SnapshotAt", "LastUpdated"] if col in history.columns]
    ordered = history.sort_values(sort_cols) if sort_cols else history.copy()
    rows = []
    tracked_fields = ["AwayML", "HomeML", "Spread", "SpreadOdds", "Total", "OverOdds", "UnderOdds"]
    for key_values, group in ordered.groupby(key_cols, dropna=False):
        if not isinstance(key_values, tuple):
            key_values = (key_values,)
        group = group.copy()
        latest_row = group.tail(1).iloc[0]
        row = {col: value for col, value in zip(key_cols, key_values)}
        row["FirstSeen"] = str(group["SnapshotAt"].iloc[0]) if "SnapshotAt" in group.columns else ""
        row["LastSnapshotAt"] = str(latest_row.get("SnapshotAt", ""))
        row["LastUpdated"] = str(latest_row.get("LastUpdated", ""))
        for field in tracked_fields:
            values = pd.to_numeric(group.get(field), errors="coerce") if field in group.columns else pd.Series(dtype=float)
            values = values.dropna()
            open_value = values.iloc[0] if not values.empty else pd.NA
            current_value = pd.to_numeric(pd.Series([latest_row.get(field)]), errors="coerce").iloc[0] if field in latest_row else pd.NA
            row[f"Open{field}"] = open_value
            row[f"Current{field}"] = current_value
            try:
                row[f"{field}Move"] = round(float(current_value) - float(open_value), 3)
            except Exception:
                row[f"{field}Move"] = pd.NA
        rows.append(row)

    current = pd.DataFrame(rows)
    if not current.empty:
        current = current.sort_values([col for col in ["Date", "Time", "Away", "Home", "Book"] if col in current.columns])
    current.to_csv(current_path, index=False)
    print(f"Tracked line movement snapshot at {history_path}")
    print(f"Updated current movement summary at {current_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch game lines from The Odds API")
    parser.add_argument("--api-key", help="The Odds API key. Prefer ODDS_API_KEY env var.")
    parser.add_argument("--sport", default=DEFAULT_SPORT, help="Odds API sport key, e.g. basketball_nba or basketball_wnba")
    parser.add_argument("--bookmakers", default=DEFAULT_BOOKMAKERS, help="Comma-separated bookmaker keys, e.g. draftkings,fanduel")
    parser.add_argument("--regions", default=DEFAULT_REGIONS, help="Comma-separated region keys, e.g. us,us2. Included for API compatibility even when bookmakers are specified.")
    parser.add_argument("--days", type=int, default=5, help="How many days ahead of events to include")
    parser.add_argument("--output", help="Primary output CSV path")
    parser.add_argument("--schedules-output", help="Optional schedule fallback output CSV path")
    parser.add_argument("--schedule-alias-output", help="Canonical schedule CSV path to keep in sync with fresh game lines")
    parser.add_argument("--skip-line-movement", action="store_true", help="Do not append this fetch to line movement tracking files.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_key = get_api_key(args.api_key)
    sport = str(args.sport or DEFAULT_SPORT).strip().lower()
    defaults = SPORT_OUTPUTS.get(sport, SPORT_OUTPUTS[DEFAULT_SPORT])
    output_path = Path(args.output).expanduser().resolve() if args.output else defaults["odds"].resolve()
    schedules_output_path = Path(args.schedules_output).expanduser().resolve() if args.schedules_output else defaults["schedules"].resolve()
    schedule_alias_output_path = Path(args.schedule_alias_output).expanduser().resolve() if args.schedule_alias_output else defaults["schedule_alias"].resolve()

    print("=" * 60)
    print("BANKROLL KINGS - Fetch Game Lines")
    print("=" * 60)
    print(f"Sport: {sport}")
    print(f"Bookmakers: {args.bookmakers}")
    print(f"Regions: {args.regions}")
    markets = SPORT_DEFAULT_MARKETS.get(sport, SPORT_DEFAULT_MARKETS[DEFAULT_SPORT])
    print(f"Markets: {', '.join(markets)}")
    print(f"Days ahead: {args.days}")
    print()

    all_rows: list[dict] = []
    fetch_failed = False
    try:
        all_rows = fetch_odds_rows(api_key, sport, args.bookmakers, markets, args.regions, args.days)
        print(f"Loaded {len(all_rows)} bookmaker rows from the standard /odds endpoint")
    except Exception as exc:
        print(f"ERROR: {exc}")
        fetch_failed = True

    df = build_dataframe(all_rows)
    if fetch_failed and df.empty:
        print()
        print("No new game-line rows were fetched. Preserving existing CSV files instead of overwriting with an empty dataset.")
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    schedules_output_path.parent.mkdir(parents=True, exist_ok=True)
    schedule_alias_output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    df.to_csv(schedules_output_path, index=False)
    build_schedule_alias(df).to_csv(schedule_alias_output_path, index=False)
    if not args.skip_line_movement:
        append_line_movement_snapshot(df, sport)

    print()
    print(f"Saved {len(df)} rows to {output_path}")
    print(f"Mirrored {len(df)} rows to {schedules_output_path}")
    print(f"Updated schedule alias at {schedule_alias_output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
