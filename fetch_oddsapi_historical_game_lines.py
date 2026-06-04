from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd

from fetch_game_lines import SPORT_DEFAULT_MARKETS, parse_event_markets
from services.env_loader import load_local_env


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_SPORT = "americanfootball_ncaaf"
SPORT_OUTPUTS = {
    "americanfootball_ncaaf": BASE_DIR / "data" / "historical" / "NCAAF_OddsAPI_GameLines_History.csv",
    "americanfootball_nfl": BASE_DIR / "data" / "historical" / "NFL_OddsAPI_GameLines_History.csv",
    "basketball_ncaab": BASE_DIR / "data" / "historical" / "CBB_OddsAPI_GameLines_History.csv",
}


def get_api_key(cli_value: str | None) -> str:
    load_local_env(BASE_DIR)
    api_key = cli_value or os.getenv("ODDS_API_KEY") or os.getenv("THE_ODDS_API_KEY")
    if not api_key:
        raise ValueError("Missing API key. Set ODDS_API_KEY or pass --api-key.")
    return api_key.strip()


def build_url(path: str, **params) -> str:
    clean_params = {key: value for key, value in params.items() if value not in [None, ""]}
    return f"https://api.the-odds-api.com{path}?{urlencode(clean_params)}"


def get_json(url: str) -> list | dict:
    with urlopen(url, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_date(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).strip())
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def snapshot_range(start_date: str, end_date: str, snapshot_hour_utc: int, interval_days: int) -> list[datetime]:
    start = parse_date(start_date).replace(hour=snapshot_hour_utc, minute=0, second=0, microsecond=0)
    end = parse_date(end_date).replace(hour=snapshot_hour_utc, minute=0, second=0, microsecond=0)
    if end < start:
        raise ValueError("end-date must be on or after start-date")
    snapshots = []
    current = start
    while current <= end:
        snapshots.append(current)
        current += timedelta(days=max(1, interval_days))
    return snapshots


def fetch_snapshot_rows(
    api_key: str,
    sport: str,
    snapshot: datetime,
    *,
    bookmakers: str,
    regions: str,
    markets: list[str],
    days_ahead: int,
) -> list[dict]:
    commence_from = snapshot.strftime("%Y-%m-%dT%H:%M:%SZ")
    commence_to = (snapshot + timedelta(days=days_ahead)).strftime("%Y-%m-%dT%H:%M:%SZ")
    snapshot_iso = snapshot.strftime("%Y-%m-%dT%H:%M:%SZ")
    url = build_url(
        f"/v4/historical/sports/{sport}/odds",
        apiKey=api_key,
        date=snapshot_iso,
        regions=regions,
        bookmakers=bookmakers,
        markets=",".join(markets),
        oddsFormat="american",
        dateFormat="iso",
        commenceTimeFrom=commence_from,
        commenceTimeTo=commence_to,
    )
    payload = get_json(url)
    if isinstance(payload, dict):
        events = payload.get("data", [])
    else:
        events = payload
    rows = []
    for event in events if isinstance(events, list) else []:
        for bookmaker in event.get("bookmakers", []):
            row = parse_event_markets(event, bookmaker)
            row["SnapshotDate"] = snapshot_iso
            row["CommenceTime"] = event.get("commence_time", "")
            row["SportKey"] = sport
            rows.append(row)
    return rows


def build_dataframe(rows: list[dict]) -> pd.DataFrame:
    columns = [
        "SnapshotDate", "Date", "Time", "CommenceTime", "SportKey",
        "Away", "Home", "AwayFull", "HomeFull",
        "AwayML", "HomeML", "Spread", "SpreadOdds",
        "Total", "OverOdds", "UnderOdds",
        "Book", "GameID", "LastUpdated",
    ]
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=columns)
    for col in ["AwayML", "HomeML", "Spread", "SpreadOdds", "Total", "OverOdds", "UnderOdds"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in columns:
        if col not in df.columns:
            df[col] = pd.NA
    df = df[columns]
    df = df.drop_duplicates(subset=["SnapshotDate", "Date", "Away", "Home", "Book"], keep="last")
    return df.sort_values(["SnapshotDate", "Date", "Time", "Away", "Home", "Book"]).reset_index(drop=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch historical game lines from The Odds API.")
    parser.add_argument("--api-key", default=None, help="The Odds API key. Prefer ODDS_API_KEY env var.")
    parser.add_argument("--sport", default=DEFAULT_SPORT, help="Odds API sport key.")
    parser.add_argument("--start-date", required=True, help="First snapshot date, YYYY-MM-DD.")
    parser.add_argument("--end-date", required=True, help="Last snapshot date, YYYY-MM-DD.")
    parser.add_argument("--snapshot-hour-utc", type=int, default=16, help="Hour of day for each historical snapshot.")
    parser.add_argument("--interval-days", type=int, default=1, help="Days between historical snapshots.")
    parser.add_argument("--days-ahead", type=int, default=7, help="Event window after each snapshot.")
    parser.add_argument("--bookmakers", default="draftkings,caesars,fanduel,betmgm")
    parser.add_argument("--regions", default="us")
    parser.add_argument("--markets", default="", help="Comma-separated markets. Defaults to sport standard markets.")
    parser.add_argument("--output", default="", help="Output CSV path.")
    args = parser.parse_args()

    api_key = get_api_key(args.api_key)
    sport = str(args.sport or DEFAULT_SPORT).strip().lower()
    markets = [item.strip() for item in args.markets.split(",") if item.strip()]
    if not markets:
        markets = SPORT_DEFAULT_MARKETS.get(sport, ["h2h", "spreads", "totals"])

    all_rows: list[dict] = []
    snapshots = snapshot_range(args.start_date, args.end_date, args.snapshot_hour_utc, args.interval_days)
    for snapshot in snapshots:
        try:
            rows = fetch_snapshot_rows(
                api_key,
                sport,
                snapshot,
                bookmakers=args.bookmakers,
                regions=args.regions,
                markets=markets,
                days_ahead=args.days_ahead,
            )
        except Exception as exc:
            print(f"[FAIL] {snapshot.date()} {exc}")
            continue
        all_rows.extend(rows)
        print(f"[OK] {snapshot.date()} rows={len(rows)}")

    df = build_dataframe(all_rows)
    output_path = Path(args.output).resolve() if args.output else SPORT_OUTPUTS.get(sport, BASE_DIR / "data" / "historical" / f"{sport}_GameLines_History.csv")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    print(f"Wrote {len(df)} rows to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
