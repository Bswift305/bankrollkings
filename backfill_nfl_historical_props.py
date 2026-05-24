"""
Bankroll Kings - Backfill Historical NFL Player Props from The Odds API
======================================================================

This script uses The Odds API historical endpoints to fetch event-level
player prop snapshots for NFL games, then joins those market rows to
historical nflverse weekly player stats so the output includes actual
results for immediate research and backtesting.

Examples:
    py backfill_nfl_historical_props.py --season 2024 --start-week 1 --end-week 18
    py backfill_nfl_historical_props.py --season 2024 --start-week 1 --end-week 4 --markets player_pass_yds,player_rush_yds,player_reception_yds,player_receptions
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd


BASE_DIR = Path(__file__).parent.resolve()
SPORT = "americanfootball_nfl"
DEFAULT_BOOKMAKERS = "draftkings"
DEFAULT_REGIONS = "us"
DEFAULT_MARKETS = [
    "player_pass_yds",
    "player_pass_attempts",
    "player_pass_completions",
    "player_pass_interceptions",
    "player_pass_tds",
    "player_rush_attempts",
    "player_rush_yds",
    "player_rush_tds",
    "player_reception_yds",
    "player_receptions",
    "player_reception_tds",
]
OUTPUT_PATH = BASE_DIR / "data" / "historical" / "NFL_Props_History.csv"
SCHEDULE_PATH = BASE_DIR / "data" / "historical" / "NFL_Games_nfldata.csv"
PLAYER_STATS_GLOB = "NFL_PlayerStats_*.csv"

TEAM_ABBR_TO_NAME = {
    "ARI": "Arizona Cardinals",
    "ATL": "Atlanta Falcons",
    "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills",
    "CAR": "Carolina Panthers",
    "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals",
    "CLE": "Cleveland Browns",
    "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos",
    "DET": "Detroit Lions",
    "GB": "Green Bay Packers",
    "HOU": "Houston Texans",
    "IND": "Indianapolis Colts",
    "JAX": "Jacksonville Jaguars",
    "KC": "Kansas City Chiefs",
    "LAC": "Los Angeles Chargers",
    "LA": "Los Angeles Rams",
    "LAR": "Los Angeles Rams",
    "LV": "Las Vegas Raiders",
    "MIA": "Miami Dolphins",
    "MIN": "Minnesota Vikings",
    "NE": "New England Patriots",
    "NO": "New Orleans Saints",
    "NYG": "New York Giants",
    "NYJ": "New York Jets",
    "PHI": "Philadelphia Eagles",
    "PIT": "Pittsburgh Steelers",
    "SEA": "Seattle Seahawks",
    "SF": "San Francisco 49ers",
    "TB": "Tampa Bay Buccaneers",
    "TEN": "Tennessee Titans",
    "WAS": "Washington Commanders",
}

STAT_CONFIG = {
    "player_pass_attempts": {"stat_label": "Pass Att", "actual_col": "attempts"},
    "player_pass_completions": {"stat_label": "Pass Comp", "actual_col": "completions"},
    "player_pass_interceptions": {"stat_label": "Pass INT", "actual_col": "passing_interceptions"},
    "player_pass_tds": {"stat_label": "Pass TDs", "actual_col": "passing_tds"},
    "player_pass_yds": {"stat_label": "Pass Yds", "actual_col": "passing_yards"},
    "player_rush_attempts": {"stat_label": "Rush Att", "actual_col": "carries"},
    "player_rush_tds": {"stat_label": "Rush TDs", "actual_col": "rushing_tds"},
    "player_rush_yds": {"stat_label": "Rush Yds", "actual_col": "rushing_yards"},
    "player_reception_tds": {"stat_label": "Rec TDs", "actual_col": "receiving_tds"},
    "player_reception_yds": {"stat_label": "Rec Yds", "actual_col": "receiving_yards"},
    "player_receptions": {"stat_label": "Receptions", "actual_col": "receptions"},
    "player_anytime_td": {"stat_label": "Anytime TD", "actual_col": "receiving_tds"},
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


def normalize_text(value) -> str:
    return str(value or "").strip().lower()


def normalize_player_lookup(value) -> str:
    text = normalize_text(value).replace("'", "").replace("-", " ")
    if not text:
        return ""
    suffixes = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v"}
    parts = [part for part in text.split() if part not in suffixes]
    if not parts:
        return text
    if len(parts) == 1:
        return parts[0]
    first_initial = parts[0][0]
    if len(parts) >= 3 and parts[-2] in {"st", "st.", "de", "van", "von"}:
        last_name = f"st.{parts[-1]}" if parts[-2] in {"st", "st."} else f"{parts[-2]} {parts[-1]}"
    else:
        last_name = parts[-1]
    return f"{first_initial}.{last_name}"


def player_lookup_candidates(value) -> list[str]:
    text = normalize_text(value).replace("'", "").replace("-", " ")
    primary = normalize_player_lookup(value)
    candidates = [primary]
    suffixes = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v"}
    parts = [part for part in text.split() if part not in suffixes]
    if len(parts) >= 2:
        last = parts[-1]
        if len(parts) >= 3 and parts[-2] in {"st", "st."}:
            last = f"st.{parts[-1]}"
        candidates.append(f"{parts[0][:2]}.{last}")
        candidates.append(f"{parts[0][0]}.{last}")
    raw = normalize_text(value).replace(" ", "")
    if raw:
        candidates.append(raw)
    deduped = []
    for candidate in candidates:
        candidate = str(candidate or "").strip().lower()
        if candidate and candidate not in deduped:
            deduped.append(candidate)
    return deduped


def normalize_team_name(value) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.upper() in TEAM_ABBR_TO_NAME:
        return TEAM_ABBR_TO_NAME[raw.upper()]
    return raw


def to_snapshot(dt_value: str, hours_before: int) -> datetime:
    game_dt = datetime.fromisoformat(str(dt_value).replace("Z", "+00:00"))
    return game_dt - timedelta(hours=hours_before)


def load_schedule(season: int, start_week: int, end_week: int, season_type: str) -> pd.DataFrame:
    if not SCHEDULE_PATH.exists():
        raise FileNotFoundError(f"Missing schedule file: {SCHEDULE_PATH}")
    df = pd.read_csv(SCHEDULE_PATH, low_memory=False)
    df["season"] = pd.to_numeric(df["season"], errors="coerce")
    df["week"] = pd.to_numeric(df["week"], errors="coerce")
    if "gameday" in df.columns:
        df["gameday"] = pd.to_datetime(df["gameday"], errors="coerce", utc=True)
    season_type = str(season_type or "REG").strip().upper()
    mask = (
        (df["season"] == season)
        & (df["week"] >= start_week)
        & (df["week"] <= end_week)
        & (df["game_type"].astype(str).str.upper() == season_type)
    )
    working = df.loc[mask, ["season", "week", "gameday", "away_team", "home_team", "game_type"]].copy()
    working["away_name"] = working["away_team"].map(TEAM_ABBR_TO_NAME).fillna(working["away_team"])
    working["home_name"] = working["home_team"].map(TEAM_ABBR_TO_NAME).fillna(working["home_team"])
    working = working.dropna(subset=["gameday"]).sort_values(["week", "gameday", "away_team", "home_team"])
    return working


def filter_schedule_by_teams(schedule: pd.DataFrame, team_filter: list[str]) -> pd.DataFrame:
    if schedule.empty or not team_filter:
        return schedule
    team_keys = {str(team).strip().upper() for team in team_filter if str(team).strip()}
    if not team_keys:
        return schedule
    mask = schedule["away_team"].astype(str).str.upper().isin(team_keys) | schedule["home_team"].astype(str).str.upper().isin(team_keys)
    return schedule.loc[mask].copy()


def load_player_stats() -> pd.DataFrame:
    files = sorted((BASE_DIR / "data" / "historical").glob(PLAYER_STATS_GLOB))
    frames = []
    for path in files:
        df = pd.read_csv(path, low_memory=False)
        if df.empty:
            continue
        df["season"] = pd.to_numeric(df["season"], errors="coerce")
        df["week"] = pd.to_numeric(df["week"], errors="coerce")
        for col in ["player_display_name", "team", "opponent_team", "season_type"]:
            if col in df.columns:
                df[col] = df[col].fillna("").astype(str).str.strip()
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True, sort=False)
    return combined


def build_actual_lookup(stats_df: pd.DataFrame) -> dict:
    lookup = {}
    if stats_df is None or stats_df.empty:
        return lookup
    for _, row in stats_df.iterrows():
        player_keys = player_lookup_candidates(row.get("player_display_name"))
        team = normalize_text(row.get("team"))
        opp = normalize_text(row.get("opponent_team"))
        season = int(row.get("season")) if pd.notna(row.get("season")) else None
        week = int(row.get("week")) if pd.notna(row.get("week")) else None
        season_type = str(row.get("season_type") or "").strip().upper()
        for player in player_keys:
            key = (season, week, season_type, player, team, opp)
            lookup[key] = row.to_dict()
    return lookup


def fetch_historical_events(api_key: str, snapshot_iso: str) -> list[dict]:
    url = build_url(
        f"/v4/historical/sports/{SPORT}/events",
        apiKey=api_key,
        date=snapshot_iso,
        dateFormat="iso",
        includeLinks="true",
    )
    payload = get_json(url)
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return data
    return payload if isinstance(payload, list) else []


def match_event(event_rows: list[dict], away_name: str, home_name: str, game_dt: pd.Timestamp) -> dict | None:
    away_key = normalize_text(away_name)
    home_key = normalize_text(home_name)
    for event in event_rows:
        event_away = normalize_text(event.get("away_team"))
        event_home = normalize_text(event.get("home_team"))
        if event_away == away_key and event_home == home_key:
            return event
    # fallback by date + team containment
    game_date = pd.Timestamp(game_dt).date()
    for event in event_rows:
        event_away = normalize_text(event.get("away_team"))
        event_home = normalize_text(event.get("home_team"))
        commence = pd.to_datetime(event.get("commence_time"), errors="coerce", utc=True)
        if pd.notna(commence) and commence.date() == game_date and away_key in event_away and home_key in event_home:
            return event
    return None


def parse_event_props(event: dict, bookmaker: dict, allowed_markets: list[str]) -> list[dict]:
    rows = []
    game = f"{event.get('away_team','')}@{event.get('home_team','')}"
    snapshot = event.get("snapshot_date") or ""
    for market in bookmaker.get("markets", []):
        market_key = market.get("key")
        if market_key not in allowed_markets or market_key not in STAT_CONFIG:
            continue

        grouped: dict[tuple[str, float], dict] = {}
        for outcome in market.get("outcomes", []):
            player = str(outcome.get("description") or "").strip()
            side = str(outcome.get("name") or "").strip().upper()
            line = outcome.get("point")
            price = outcome.get("price")
            if not player or line in [None, ""] or side not in {"OVER", "UNDER"}:
                continue
            key = (player, float(line))
            if key not in grouped:
                grouped[key] = {
                    "EventId": event.get("id", ""),
                    "SnapshotDate": snapshot,
                    "CommenceTime": event.get("commence_time", ""),
                    "Game": game,
                    "AwayTeam": event.get("away_team", ""),
                    "HomeTeam": event.get("home_team", ""),
                    "AwayAbbr": event.get("away_abbr", ""),
                    "HomeAbbr": event.get("home_abbr", ""),
                    "Player": player,
                    "Stat": STAT_CONFIG[market_key]["stat_label"],
                    "MarketKey": market_key,
                    "Line": float(line),
                    "Book": bookmaker.get("title") or bookmaker.get("key", ""),
                    "OverOdds": pd.NA,
                    "UnderOdds": pd.NA,
                }
            if side == "OVER":
                grouped[key]["OverOdds"] = price
            else:
                grouped[key]["UnderOdds"] = price
        rows.extend(grouped.values())
    return rows


def fetch_historical_event_props(api_key: str, event: dict, snapshot_iso: str, bookmakers: str, markets: list[str], regions: str) -> list[dict]:
    url = build_url(
        f"/v4/historical/sports/{SPORT}/events/{event['id']}/odds",
        apiKey=api_key,
        regions=regions,
        bookmakers=bookmakers,
        markets=",".join(markets),
        oddsFormat="american",
        dateFormat="iso",
        date=snapshot_iso,
    )
    payload = get_json(url)
    if isinstance(payload, dict):
        data_payload = payload.get("data", {}) if isinstance(payload.get("data"), dict) else {}
        data_payload["snapshot_date"] = snapshot_iso
        data_payload["away_abbr"] = event.get("away_abbr", "")
        data_payload["home_abbr"] = event.get("home_abbr", "")
        bookmakers_payload = data_payload.get("bookmakers", [])
    else:
        bookmakers_payload = []
        data_payload = {
            "snapshot_date": snapshot_iso,
            "away_abbr": event.get("away_abbr", ""),
            "home_abbr": event.get("home_abbr", ""),
        }

    all_rows = []
    for bookmaker in bookmakers_payload:
        all_rows.extend(parse_event_props(data_payload, bookmaker, markets))
    return all_rows


def attach_actuals(rows: list[dict], actual_lookup: dict, season: int, week: int, season_type: str) -> list[dict]:
    enriched = []
    for row in rows:
        player_keys = player_lookup_candidates(row.get("Player"))
        away = normalize_text(row.get("AwayTeam"))
        home = normalize_text(row.get("HomeTeam"))
        stat_key = STAT_CONFIG.get(row.get("MarketKey"), {}).get("actual_col")
        actual_value = pd.NA
        team = ""
        opponent = ""
        home_abbr = str(row.get("HomeAbbr") or "").strip().upper()
        away_abbr = str(row.get("AwayAbbr") or "").strip().upper()

        for team_abbr, opp_abbr in [
            (home_abbr, away_abbr),
            (away_abbr, home_abbr),
        ]:
            if not team_abbr or not opp_abbr:
                continue
            for player in player_keys:
                key = (season, week, season_type, player, team_abbr.lower(), opp_abbr.lower())
                player_row = actual_lookup.get(key)
                if player_row:
                    team = team_abbr
                    opponent = opp_abbr
                    if stat_key and stat_key in player_row:
                        actual_value = pd.to_numeric(player_row.get(stat_key), errors="coerce")
                    break
            if team:
                break

        result = dict(row)
        result["Season"] = season
        result["Week"] = week
        result["SeasonType"] = season_type
        result["Team"] = team
        result["Opponent"] = opponent
        result["Actual"] = actual_value
        enriched.append(result)
    return enriched


def build_dataframe(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=[
            "SnapshotDate", "Season", "Week", "SeasonType", "CommenceTime", "EventId",
            "Player", "Team", "Opponent", "Stat", "MarketKey", "Line", "Actual",
            "Book", "OverOdds", "UnderOdds", "Game", "AwayTeam", "HomeTeam",
            "AwayAbbr", "HomeAbbr"
        ])
    ordered = [
        "SnapshotDate", "Season", "Week", "SeasonType", "CommenceTime", "EventId",
        "Player", "Team", "Opponent", "Stat", "MarketKey", "Line", "Actual",
        "Book", "OverOdds", "UnderOdds", "Game", "AwayTeam", "HomeTeam",
        "AwayAbbr", "HomeAbbr"
    ]
    for col in ordered:
        if col not in df.columns:
            df[col] = pd.NA
    df = df[ordered]
    df = df.drop_duplicates(subset=["SnapshotDate", "EventId", "Player", "Stat", "Line", "Book"], keep="last")
    return df.sort_values(["Season", "Week", "Game", "Book", "Player", "Stat"]).reset_index(drop=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill historical NFL player props from The Odds API")
    parser.add_argument("--api-key", help="The Odds API key. Prefer ODDS_API_KEY env var.")
    parser.add_argument("--season", type=int, required=True, help="NFL season year to backfill, e.g. 2024")
    parser.add_argument("--start-week", type=int, default=1, help="Start week")
    parser.add_argument("--end-week", type=int, default=18, help="End week")
    parser.add_argument("--season-type", default="REG", help="Season type, usually REG or POST")
    parser.add_argument("--snapshot-hours-before", type=int, default=18, help="Hours before kickoff to query historical snapshot")
    parser.add_argument("--bookmakers", default=DEFAULT_BOOKMAKERS, help="Comma-separated bookmaker keys")
    parser.add_argument("--regions", default=DEFAULT_REGIONS, help="Regions, usually us")
    parser.add_argument("--markets", default=",".join(DEFAULT_MARKETS), help="Comma-separated historical prop markets")
    parser.add_argument("--output", help="Output CSV path")
    parser.add_argument("--sleep-ms", type=int, default=300, help="Pause between event odds requests")
    parser.add_argument("--max-games", type=int, default=0, help="Optional cap for testing")
    parser.add_argument("--teams", default="", help="Optional comma-separated team abbreviations to limit schedule rows, e.g. LA,LAC")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_key = get_api_key(args.api_key)
    output_path = Path(args.output).expanduser().resolve() if args.output else OUTPUT_PATH.resolve()
    markets = [m.strip() for m in str(args.markets or "").split(",") if m.strip()]
    season_type = str(args.season_type or "REG").strip().upper()
    team_filter = [team.strip().upper() for team in str(args.teams or "").split(",") if team.strip()]

    schedule = load_schedule(args.season, args.start_week, args.end_week, season_type)
    schedule = filter_schedule_by_teams(schedule, team_filter)
    if schedule.empty:
        print("No schedule rows found for that season/week range.")
        return 1

    if args.max_games and args.max_games > 0:
        schedule = schedule.head(int(args.max_games)).copy()

    stats_df = load_player_stats()
    actual_lookup = build_actual_lookup(stats_df)

    print("=" * 72)
    print("BANKROLL KINGS - Backfill Historical NFL Player Props")
    print("=" * 72)
    print(f"Season: {args.season} {season_type}")
    print(f"Weeks: {args.start_week}-{args.end_week}")
    print(f"Games queued: {len(schedule)}")
    if team_filter:
        print(f"Team filter: {', '.join(team_filter)}")
    print(f"Bookmakers: {args.bookmakers}")
    print(f"Markets: {', '.join(markets)}")
    print(f"Snapshot lead: {args.snapshot_hours_before} hours")

    all_rows: list[dict] = []
    missing_events = 0
    failed_events = 0

    for idx, game in enumerate(schedule.itertuples(index=False), start=1):
        snapshot_dt = to_snapshot(game.gameday.isoformat(), args.snapshot_hours_before)
        snapshot_iso = snapshot_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        away_name = normalize_team_name(game.away_name)
        home_name = normalize_team_name(game.home_name)
        event_stub = {
            "away_abbr": str(game.away_team).strip().upper(),
            "home_abbr": str(game.home_team).strip().upper(),
        }
        print(f"[{idx}/{len(schedule)}] Week {int(game.week)} {away_name} @ {home_name} | snapshot {snapshot_iso}")
        try:
            events = fetch_historical_events(api_key, snapshot_iso)
            event = match_event(events, away_name, home_name, game.gameday)
            if not event:
                print("  No matching historical event id found")
                missing_events += 1
                continue
            event.update(event_stub)
            event_rows = fetch_historical_event_props(
                api_key=api_key,
                event=event,
                snapshot_iso=snapshot_iso,
                bookmakers=args.bookmakers,
                markets=markets,
                regions=args.regions,
            )
            event_rows = attach_actuals(event_rows, actual_lookup, int(game.season), int(game.week), season_type)
            print(f"  Loaded {len(event_rows)} prop rows")
            all_rows.extend(event_rows)
        except Exception as exc:
            print(f"  Failed: {exc}")
            failed_events += 1
        time.sleep(max(args.sleep_ms, 0) / 1000.0)

    df = build_dataframe(all_rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        existing = pd.read_csv(output_path, low_memory=False)
        df = pd.concat([existing, df], ignore_index=True, sort=False)
        df = build_dataframe(df.to_dict("records"))
    df.to_csv(output_path, index=False)

    print()
    print(f"Saved {len(df)} total historical prop rows to {output_path}")
    print(f"Missing events: {missing_events}")
    print(f"Failed events: {failed_events}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
