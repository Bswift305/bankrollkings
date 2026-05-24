"""
Bankroll Kings - Fetch Player Props from The Odds API
=====================================================

Examples:
    $env:ODDS_API_KEY="your_key_here"; py fetch_player_props.py
    py fetch_player_props.py --sport basketball_nba --bookmakers draftkings,fanduel --days 4
    py fetch_player_props.py --sport americanfootball_nfl --bookmakers draftkings,caesars,fanduel,betmgm --days 7
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd
from services.env_loader import load_local_env


BASE_DIR = Path(__file__).parent.resolve()
load_local_env(BASE_DIR)
SPORT_OUTPUTS = {
    "basketball_nba": BASE_DIR / "data" / "props" / "NBA_Props.csv",
    "basketball_wnba": BASE_DIR / "data" / "props" / "WNBA_Props.csv",
    "americanfootball_nfl": BASE_DIR / "data" / "props" / "NFL_Props.csv",
    "americanfootball_ncaaf": BASE_DIR / "data" / "props" / "NCAAF_Props.csv",
    "baseball_mlb": BASE_DIR / "data" / "props" / "MLB_Props.csv",
}
DEFAULT_SPORT = "basketball_nba"
DEFAULT_BOOKMAKERS = "draftkings"
DEFAULT_REGIONS = "us"
SPORT_DEFAULT_MARKETS = {
    "basketball_nba": [
        "player_points",
        "player_rebounds",
        "player_assists",
        "player_threes",
        "player_steals",
        "player_blocks",
    ],
    "basketball_wnba": [
        "player_points",
        "player_rebounds",
        "player_assists",
        "player_threes",
        "player_steals",
        "player_blocks",
    ],
    "americanfootball_nfl": [
        "player_pass_yds",
        "player_pass_tds",
        "player_pass_completions",
        "player_rush_yds",
        "player_rush_attempts",
        "player_receptions",
        "player_reception_yds",
        "player_anytime_td",
    ],
    "americanfootball_ncaaf": [
        "player_pass_yds",
        "player_pass_tds",
        "player_pass_completions",
        "player_rush_yds",
        "player_rush_attempts",
        "player_receptions",
        "player_reception_yds",
        "player_anytime_td",
    ],
    "baseball_mlb": [
        "batter_hits",
        "batter_total_bases",
        "batter_home_runs",
        "batter_rbis",
        "batter_runs_scored",
        "batter_stolen_bases",
        "batter_walks",
        "batter_strikeouts",
        "batter_singles",
        "batter_doubles",
        "batter_triples",
        "batter_hits_runs_rbis",
        "pitcher_strikeouts",
        "pitcher_hits_allowed",
        "pitcher_walks",
        "pitcher_earned_runs",
        "pitcher_outs",
        "pitcher_record_a_win",
    ],
}

SPORT_REQUIRED_MARKETS = {
    "baseball_mlb": [
        "batter_hits",
        "batter_total_bases",
        "batter_home_runs",
        "batter_rbis",
        "batter_runs_scored",
        "batter_stolen_bases",
        "batter_walks",
        "batter_strikeouts",
        "batter_singles",
        "batter_doubles",
        "batter_triples",
        "batter_hits_runs_rbis",
        "pitcher_strikeouts",
        "pitcher_hits_allowed",
        "pitcher_walks",
        "pitcher_earned_runs",
        "pitcher_outs",
        "pitcher_record_a_win",
    ],
}

MARKET_STAT_MAP = {
    "player_points": "PTS",
    "player_rebounds": "REB",
    "player_assists": "AST",
    "player_threes": "3PM",
    "player_steals": "STL",
    "player_blocks": "BLK",
    "player_pass_yds": "Pass Yds",
    "player_pass_tds": "Pass TDs",
    "player_pass_completions": "Pass Completions",
    "player_rush_yds": "Rush Yds",
    "player_rush_attempts": "Rush Att",
    "player_receptions": "Receptions",
    "player_reception_yds": "Rec Yds",
    "player_anytime_td": "Anytime TD",
    "batter_hits": "Hits",
    "batter_total_bases": "Total Bases",
    "batter_home_runs": "Home Runs",
    "batter_rbis": "RBIs",
    "batter_runs_scored": "Runs",
    "batter_stolen_bases": "Stolen Bases",
    "batter_walks": "Batter Walks",
    "batter_strikeouts": "Batter Strikeouts",
    "batter_singles": "Singles",
    "batter_doubles": "Doubles",
    "batter_triples": "Triples",
    "batter_hits_runs_rbis": "Hits + Runs + RBIs",
    "pitcher_strikeouts": "Pitcher Ks",
    "pitcher_hits_allowed": "Pitcher Hits Allowed",
    "pitcher_walks": "Pitcher Walks",
    "pitcher_earned_runs": "Pitcher Earned Runs",
    "pitcher_outs": "Pitcher Outs",
    "pitcher_record_a_win": "Pitcher Win",
}

BOOKMAKER_TITLES = {
    "draftkings": "DraftKings",
    "fanduel": "FanDuel",
    "betmgm": "BetMGM",
    "caesars": "Caesars",
    "williamhill_us": "Caesars",
    "betrivers": "BetRivers",
    "fanatics": "Fanatics",
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


def fetch_events(api_key: str, sport: str, days: int) -> list[dict]:
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


def to_iso_local(value: str | None) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(value)


def build_game_label(event: dict) -> str:
    away = event.get("away_team", "")
    home = event.get("home_team", "")
    return f"{away}@{home}"


def normalize_team_name(team: str) -> str:
    return str(team or "").strip()


def parse_market_rows(event: dict, bookmaker: dict, allowed_markets: Iterable[str]) -> list[dict]:
    event_game = build_game_label(event)
    commence_time = to_iso_local(event.get("commence_time"))
    fetched_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    rows = []

    for market in bookmaker.get("markets", []):
        market_key = market.get("key")
        if market_key not in allowed_markets or market_key not in MARKET_STAT_MAP:
            continue

        over_under_map: dict[tuple[str, float], dict] = {}
        for outcome in market.get("outcomes", []):
            player = str(outcome.get("description") or "").strip()
            side = str(outcome.get("name") or "").strip().upper()
            line = outcome.get("point")
            price = outcome.get("price")

            if not player or side not in {"OVER", "UNDER", "YES", "NO"}:
                continue
            if side in {"YES", "NO"} and line in [None, ""]:
                line = 0.5
            if line in [None, ""]:
                continue

            key = (player, float(line))
            if key not in over_under_map:
                over_under_map[key] = {
                    "Player": player,
                    "Team": "",
                    "Stat": MARKET_STAT_MAP[market_key],
                    "MarketKey": market_key,
                    "Line": float(line),
                    "Game": event_game,
                    "Book": bookmaker.get("title") or BOOKMAKER_TITLES.get(bookmaker.get("key", ""), bookmaker.get("key", "")),
                    "LastUpdated": to_iso_local(bookmaker.get("last_update")) or fetched_at,
                    "CurrentLine": float(line),
                    "OverOdds": pd.NA,
                    "UnderOdds": pd.NA,
                }

            if side in {"OVER", "YES"}:
                over_under_map[key]["OverOdds"] = price
            elif side in {"UNDER", "NO"}:
                over_under_map[key]["UnderOdds"] = price

        rows.extend(over_under_map.values())

    return rows


def infer_teams(rows: list[dict], event: dict) -> list[dict]:
    away = normalize_team_name(event.get("away_team"))
    home = normalize_team_name(event.get("home_team"))
    game = build_game_label(event)

    team_hints = {}
    for side in [away, home]:
        if side:
            team_hints[side.upper()] = side

    for row in rows:
        row["Game"] = game
        player_name = row["Player"]
        if "@" in game:
            away_team, home_team = game.split("@", 1)
            if row["Team"] == "":
                # Keep blank if we cannot infer from source.
                # App derives the live team from game logs anyway.
                row["Team"] = ""
            row["AwayTeam"] = away_team
            row["HomeTeam"] = home_team
    return rows


def fetch_event_props(api_key: str, sport: str, event: dict, bookmakers: str, markets: list[str], regions: str) -> list[dict]:
    url = build_url(
        f"/v4/sports/{sport}/events/{event['id']}/odds",
        apiKey=api_key,
        regions=regions,
        bookmakers=bookmakers,
        markets=",".join(markets),
        oddsFormat="american",
        dateFormat="iso",
    )
    try:
        payload = get_json(url)
        all_rows = []
        for bookmaker in payload.get("bookmakers", []):
            bookmaker_rows = parse_market_rows(event, bookmaker, markets)
            all_rows.extend(bookmaker_rows)
        return infer_teams(all_rows, event)
    except Exception as combined_error:
        # If one future market key is rejected by the provider, do not lose the
        # full slate. Probe each market separately and keep the valid ones.
        fallback_rows: list[dict] = []
        fallback_errors: list[str] = []
        for market_key in markets:
            single_url = build_url(
                f"/v4/sports/{sport}/events/{event['id']}/odds",
                apiKey=api_key,
                regions=regions,
                bookmakers=bookmakers,
                markets=market_key,
                oddsFormat="american",
                dateFormat="iso",
            )
            try:
                single_payload = get_json(single_url)
            except Exception as market_error:
                fallback_errors.append(f"{market_key}: {market_error}")
                continue
            for bookmaker in single_payload.get("bookmakers", []):
                fallback_rows.extend(parse_market_rows(event, bookmaker, [market_key]))
        if fallback_rows:
            if fallback_errors:
                print(f"  Market key audit fallback kept valid markets; unavailable keys: {len(fallback_errors)}")
            return infer_teams(fallback_rows, event)
        raise combined_error


def build_dataframe(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=[
            "Player", "Team", "Stat", "MarketKey", "Line", "Game", "Book", "LastUpdated",
            "OpenLine", "CurrentLine", "CloseLine", "OpenOverOdds", "OpenUnderOdds",
            "OverOdds", "UnderOdds", "CloseOverOdds", "CloseUnderOdds",
            "BetLine", "BetOverOdds", "BetUnderOdds", "BetBook", "BetTime"
        ])

    df["Line"] = pd.to_numeric(df["Line"], errors="coerce")
    df["CurrentLine"] = pd.to_numeric(df["CurrentLine"], errors="coerce")
    df["OverOdds"] = pd.to_numeric(df["OverOdds"], errors="coerce")
    df["UnderOdds"] = pd.to_numeric(df["UnderOdds"], errors="coerce")

    for column in [
        "OpenLine", "CloseLine", "OpenOverOdds", "OpenUnderOdds",
        "CloseOverOdds", "CloseUnderOdds", "BetLine", "BetOverOdds",
        "BetUnderOdds", "BetBook", "BetTime"
    ]:
        if column not in df.columns:
            df[column] = pd.NA

    if "Team" not in df.columns:
        df["Team"] = ""
    if "MarketKey" not in df.columns:
        df["MarketKey"] = ""

    ordered_columns = [
        "Player", "Team", "Stat", "MarketKey", "Line", "Game", "Book", "LastUpdated",
        "OpenLine", "CurrentLine", "CloseLine", "OpenOverOdds", "OpenUnderOdds",
        "OverOdds", "UnderOdds", "CloseOverOdds", "CloseUnderOdds",
        "BetLine", "BetOverOdds", "BetUnderOdds", "BetBook", "BetTime"
    ]
    df = df[ordered_columns]
    df = df.drop_duplicates(subset=["Player", "Stat", "MarketKey", "Line", "Game", "Book"], keep="last")
    return df.sort_values(["Game", "Book", "Player", "Stat", "Line"]).reset_index(drop=True)


def write_market_coverage(df: pd.DataFrame, sport: str, requested_markets: list[str], output_path: Path) -> None:
    required = SPORT_REQUIRED_MARKETS.get(sport, requested_markets)
    rows = []
    if df is not None and not df.empty and "MarketKey" in df.columns:
        working = df.copy()
        working["MarketKey"] = working["MarketKey"].fillna("").astype(str)
        counts = working["MarketKey"].value_counts().to_dict()
        book_counts = working.groupby("MarketKey")["Book"].nunique().to_dict() if "Book" in working.columns else {}
        over_counts = working.groupby("MarketKey")["OverOdds"].apply(lambda s: int(pd.to_numeric(s, errors="coerce").notna().sum())).to_dict() if "OverOdds" in working.columns else {}
        under_counts = working.groupby("MarketKey")["UnderOdds"].apply(lambda s: int(pd.to_numeric(s, errors="coerce").notna().sum())).to_dict() if "UnderOdds" in working.columns else {}
    else:
        counts = {}
        book_counts = {}
        over_counts = {}
        under_counts = {}
    fetched_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    for market in required:
        row_count = int(counts.get(market, 0) or 0)
        over_count = int(over_counts.get(market, 0) or 0)
        under_count = int(under_counts.get(market, 0) or 0)
        if row_count > 0 and over_count > 0 and under_count == 0:
            price_format = "ONE_SIDED_YES"
        elif row_count > 0 and over_count > 0 and under_count > 0:
            price_format = "TWO_WAY"
        elif row_count > 0:
            price_format = "PARTIAL"
        else:
            price_format = "NO_ROWS"
        missing_reason = ""
        if row_count == 0:
            missing_reason = "Requested key returned no rows from selected books today" if market in requested_markets else "Required market was not requested"
        rows.append({
            "Sport": sport,
            "MarketKey": market,
            "Stat": MARKET_STAT_MAP.get(market, market),
            "Requested": market in requested_markets,
            "Rows": row_count,
            "Books": int(book_counts.get(market, 0) or 0),
            "OverRows": over_count,
            "UnderRows": under_count,
            "PriceFormat": price_format,
            "Status": "LIVE" if row_count > 0 else "MISSING",
            "MissingReason": missing_reason,
            "LastChecked": fetched_at,
        })
    coverage_path = output_path.parent.parent / "tracking" / f"{output_path.stem}_MarketCoverage.csv"
    coverage_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(coverage_path, index=False)
    missing = [row["Stat"] for row in rows if row["Status"] == "MISSING"]
    if missing:
        print(f"Missing required markets: {', '.join(missing)}")
    print(f"Market coverage written to {coverage_path}")


def load_existing_history(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def merge_market_history(df: pd.DataFrame, existing: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    if existing is None or existing.empty:
        working = df.copy()
        working["OpenLine"] = working["OpenLine"].where(working["OpenLine"].notna(), working["CurrentLine"])
        working["OpenOverOdds"] = working["OpenOverOdds"].where(working["OpenOverOdds"].notna(), working["OverOdds"])
        working["OpenUnderOdds"] = working["OpenUnderOdds"].where(working["OpenUnderOdds"].notna(), working["UnderOdds"])
        return working

    existing = existing.copy()
    for col in [
        "Player", "Stat", "MarketKey", "Game", "Book",
        "OpenLine", "CurrentLine", "CloseLine", "OpenOverOdds", "OpenUnderOdds",
        "OverOdds", "UnderOdds", "CloseOverOdds", "CloseUnderOdds"
    ]:
        if col not in existing.columns:
            existing[col] = pd.NA

    existing = existing.sort_values(["Game", "Book", "Player", "Stat", "LastUpdated"], na_position="last")
    latest_lookup = {}
    for _, row in existing.iterrows():
        key = (
            str(row.get("Player", "")).strip(),
            str(row.get("Stat", "")).strip(),
            str(row.get("MarketKey", "")).strip(),
            str(row.get("Game", "")).strip(),
            str(row.get("Book", "")).strip(),
        )
        latest_lookup[key] = row

    merged_rows = []
    for _, row in df.iterrows():
        row = row.copy()
        key = (
            str(row.get("Player", "")).strip(),
            str(row.get("Stat", "")).strip(),
            str(row.get("MarketKey", "")).strip(),
            str(row.get("Game", "")).strip(),
            str(row.get("Book", "")).strip(),
        )
        previous = latest_lookup.get(key)

        if previous is not None:
            previous_open_line = previous.get("OpenLine")
            previous_current_line = previous.get("CurrentLine")
            previous_open_over = previous.get("OpenOverOdds")
            previous_open_under = previous.get("OpenUnderOdds")
            previous_over = previous.get("OverOdds")
            previous_under = previous.get("UnderOdds")
            previous_close_line = previous.get("CloseLine")
            previous_close_over = previous.get("CloseOverOdds")
            previous_close_under = previous.get("CloseUnderOdds")

            row["OpenLine"] = previous_open_line if pd.notna(previous_open_line) else row.get("CurrentLine")
            row["OpenOverOdds"] = previous_open_over if pd.notna(previous_open_over) else row.get("OverOdds")
            row["OpenUnderOdds"] = previous_open_under if pd.notna(previous_open_under) else row.get("UnderOdds")

            line_changed = pd.notna(previous_current_line) and pd.notna(row.get("CurrentLine")) and float(previous_current_line) != float(row.get("CurrentLine"))
            over_changed = pd.notna(previous_over) and pd.notna(row.get("OverOdds")) and float(previous_over) != float(row.get("OverOdds"))
            under_changed = pd.notna(previous_under) and pd.notna(row.get("UnderOdds")) and float(previous_under) != float(row.get("UnderOdds"))

            if line_changed or over_changed or under_changed:
                row["CloseLine"] = previous_current_line
                row["CloseOverOdds"] = previous_over
                row["CloseUnderOdds"] = previous_under
            else:
                row["CloseLine"] = previous_close_line
                row["CloseOverOdds"] = previous_close_over
                row["CloseUnderOdds"] = previous_close_under
        else:
            row["OpenLine"] = row.get("CurrentLine")
            row["OpenOverOdds"] = row.get("OverOdds")
            row["OpenUnderOdds"] = row.get("UnderOdds")

        merged_rows.append(row)

    merged = pd.DataFrame(merged_rows)
    return merged


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch player props from The Odds API")
    parser.add_argument("--api-key", help="The Odds API key. Prefer ODDS_API_KEY env var.")
    parser.add_argument("--sport", default=DEFAULT_SPORT, help="Odds API sport key, e.g. basketball_nba or basketball_wnba")
    parser.add_argument("--bookmakers", default=DEFAULT_BOOKMAKERS, help="Comma-separated bookmaker keys, e.g. draftkings,fanduel")
    parser.add_argument("--regions", default=DEFAULT_REGIONS, help="Comma-separated region keys, e.g. us,us2. Included for API compatibility even when bookmakers are specified.")
    parser.add_argument("--days", type=int, default=5, help="How many days ahead of events to include")
    parser.add_argument("--output", help="Output CSV path")
    parser.add_argument("--markets", help="Comma-separated market keys")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_key = get_api_key(args.api_key)
    sport = str(args.sport or DEFAULT_SPORT).strip().lower()
    default_output = SPORT_OUTPUTS.get(sport, SPORT_OUTPUTS[DEFAULT_SPORT])
    output_path = Path(args.output).expanduser().resolve() if args.output else default_output.resolve()
    default_markets = SPORT_DEFAULT_MARKETS.get(sport, SPORT_DEFAULT_MARKETS[DEFAULT_SPORT])
    markets_arg = args.markets if args.markets is not None else ",".join(default_markets)
    markets = [market.strip() for market in markets_arg.split(",") if market.strip()]

    print("=" * 60)
    print("BANKROLL KINGS - Fetch Player Props")
    print("=" * 60)
    print(f"Sport: {sport}")
    print(f"Bookmakers: {args.bookmakers}")
    print(f"Regions: {args.regions}")
    print(f"Markets: {', '.join(markets)}")

    events = fetch_events(api_key, sport, args.days)
    print(f"Found {len(events)} events in the next {args.days} days")

    all_rows: list[dict] = []
    error_count = 0
    for event in events:
        game = build_game_label(event)
        print(f"Fetching props for {game}")
        try:
            event_rows = fetch_event_props(api_key, sport, event, args.bookmakers, markets, args.regions)
            print(f"  Loaded {len(event_rows)} rows")
            all_rows.extend(event_rows)
        except Exception as exc:
            print(f"  Skipped {game}: {exc}")
            error_count += 1

    df = build_dataframe(all_rows)
    if error_count and df.empty:
        print()
        print("No new prop rows were fetched. Preserving existing CSV instead of overwriting with an empty dataset.")
        return 1

    existing = load_existing_history(output_path)
    df = merge_market_history(df, existing)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    write_market_coverage(df, sport, markets, output_path)

    print(f"Saved {len(df)} props to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
