"""
Bankroll Kings - Fetch Futures / Outrights Odds
================================================

Fetches tournament/championship futures from The Odds API `outrights` market.

Examples:
    py -3 fetch_futures_odds.py
    py -3 fetch_futures_odds.py --sports americanfootball_nfl_super_bowl_winner,baseball_mlb_world_series_winner
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd

from services.env_loader import load_local_env


BASE_DIR = Path(__file__).parent.resolve()
load_local_env(BASE_DIR)

DEFAULT_BOOKMAKERS = "draftkings,caesars,fanduel,betmgm"
DEFAULT_REGIONS = "us"
DEFAULT_GROUPS = {"American Football", "Basketball", "Baseball"}
DEFAULT_OUTPUT = BASE_DIR / "data" / "futures" / "Futures_Odds.csv"
DEFAULT_SPORTS_OUTPUT = BASE_DIR / "data" / "futures" / "Futures_Sports.csv"
HISTORY_OUTPUT = BASE_DIR / "data" / "tracking" / "Futures_LineMovementHistory.csv"
CURRENT_OUTPUT = BASE_DIR / "data" / "tracking" / "Futures_LineMovementCurrent.csv"


def get_api_key(cli_value: str | None) -> str:
    api_key = cli_value or os.getenv("ODDS_API_KEY") or os.getenv("THE_ODDS_API_KEY")
    if not api_key:
        raise ValueError("Missing API key. Set ODDS_API_KEY or pass --api-key.")
    return api_key.strip()


def build_url(path: str, **params) -> str:
    clean_params = {k: v for k, v in params.items() if v not in [None, ""]}
    return f"https://api.the-odds-api.com{path}?{urlencode(clean_params)}"


def get_json(url: str) -> list | dict:
    with urlopen(url, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def to_iso_local(value: str | None) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(value)


def fetch_sports(api_key: str, include_inactive: bool = False) -> list[dict]:
    url = build_url("/v4/sports", apiKey=api_key, all="true" if include_inactive else "")
    payload = get_json(url)
    return payload if isinstance(payload, list) else []


def select_outright_sports(sports: list[dict], groups: set[str] | None = None, include_inactive: bool = False) -> list[dict]:
    rows = []
    for sport in sports:
        if not sport.get("has_outrights"):
            continue
        if not include_inactive and not sport.get("active", False):
            continue
        if groups and sport.get("group") not in groups:
            continue
        rows.append(sport)
    return sorted(rows, key=lambda item: (str(item.get("group", "")), str(item.get("title", ""))))


def fetch_outright_rows(api_key: str, sport: dict, bookmakers: str, regions: str) -> list[dict]:
    sport_key = str(sport.get("key", "")).strip()
    if not sport_key:
        return []
    url = build_url(
        f"/v4/sports/{sport_key}/odds",
        apiKey=api_key,
        regions=regions,
        bookmakers=bookmakers,
        markets="outrights",
        oddsFormat="american",
        dateFormat="iso",
    )
    payload = get_json(url)
    if not isinstance(payload, list):
        return []

    rows: list[dict] = []
    for event in payload:
        event_id = event.get("id", "")
        commence_time = to_iso_local(event.get("commence_time"))
        event_name = (
            event.get("home_team")
            or event.get("away_team")
            or event.get("sport_title")
            or sport.get("title", "")
        )
        for bookmaker in event.get("bookmakers", []):
            book_key = bookmaker.get("key", "")
            book_title = bookmaker.get("title", "") or book_key
            last_updated = to_iso_local(bookmaker.get("last_update"))
            for market in bookmaker.get("markets", []):
                market_key = market.get("key", "")
                market_last_updated = to_iso_local(market.get("last_update")) or last_updated
                for outcome in market.get("outcomes", []):
                    rows.append(
                        {
                            "SportKey": sport_key,
                            "SportGroup": sport.get("group", ""),
                            "SportTitle": sport.get("title", ""),
                            "SportDescription": sport.get("description", ""),
                            "EventID": event_id,
                            "EventName": event_name,
                            "CommenceTime": commence_time,
                            "MarketKey": market_key,
                            "Outcome": outcome.get("name", ""),
                            "Price": outcome.get("price", pd.NA),
                            "Point": outcome.get("point", pd.NA),
                            "BookKey": book_key,
                            "Book": book_title,
                            "LastUpdated": market_last_updated,
                        }
                    )
    return rows


def build_dataframe(rows: list[dict]) -> pd.DataFrame:
    columns = [
        "SportKey",
        "SportGroup",
        "SportTitle",
        "SportDescription",
        "EventID",
        "EventName",
        "CommenceTime",
        "MarketKey",
        "Outcome",
        "Price",
        "Point",
        "BookKey",
        "Book",
        "LastUpdated",
    ]
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=columns)
    df["Price"] = pd.to_numeric(df["Price"], errors="coerce")
    df["Point"] = pd.to_numeric(df["Point"], errors="coerce")
    df = df[columns]
    df = df.drop_duplicates(
        subset=["SportKey", "EventID", "MarketKey", "Outcome", "Book"],
        keep="last",
    )
    return df.sort_values(["SportGroup", "SportTitle", "MarketKey", "Outcome", "Book"]).reset_index(drop=True)


def write_sports_catalog(sports: list[dict], path: Path) -> None:
    columns = ["key", "group", "title", "description", "active", "has_outrights"]
    df = pd.DataFrame(sports)
    if df.empty:
        df = pd.DataFrame(columns=columns)
    else:
        for col in columns:
            if col not in df.columns:
                df[col] = ""
        df = df[columns].sort_values(["group", "title", "key"]).reset_index(drop=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def append_futures_movement_snapshot(df: pd.DataFrame) -> None:
    if df is None or df.empty:
        return
    HISTORY_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    snapshot_at = datetime.now().astimezone().isoformat(timespec="seconds")
    snapshot = df.copy()
    snapshot.insert(0, "SnapshotAt", snapshot_at)

    if HISTORY_OUTPUT.exists():
        try:
            history = pd.read_csv(HISTORY_OUTPUT)
        except Exception:
            history = pd.DataFrame()
        history = pd.concat([history, snapshot], ignore_index=True, sort=False)
    else:
        history = snapshot

    dedupe_cols = ["SnapshotAt", "SportKey", "EventID", "MarketKey", "Outcome", "Book"]
    history = history.drop_duplicates(subset=[col for col in dedupe_cols if col in history.columns], keep="last")
    history.to_csv(HISTORY_OUTPUT, index=False)

    key_cols = ["SportKey", "SportTitle", "EventID", "EventName", "MarketKey", "Outcome", "Book"]
    sort_cols = [col for col in ["SnapshotAt", "LastUpdated"] if col in history.columns]
    ordered = history.sort_values(sort_cols) if sort_cols else history.copy()
    rows = []
    for key_values, group in ordered.groupby(key_cols, dropna=False):
        if not isinstance(key_values, tuple):
            key_values = (key_values,)
        latest = group.tail(1).iloc[0]
        prices = pd.to_numeric(group.get("Price"), errors="coerce").dropna()
        open_price = prices.iloc[0] if not prices.empty else pd.NA
        current_price = pd.to_numeric(pd.Series([latest.get("Price")]), errors="coerce").iloc[0]
        row = {col: value for col, value in zip(key_cols, key_values)}
        row["FirstSeen"] = str(group["SnapshotAt"].iloc[0]) if "SnapshotAt" in group.columns else ""
        row["LastSnapshotAt"] = str(latest.get("SnapshotAt", ""))
        row["LastUpdated"] = str(latest.get("LastUpdated", ""))
        row["OpenPrice"] = open_price
        row["CurrentPrice"] = current_price
        try:
            row["PriceMove"] = round(float(current_price) - float(open_price), 3)
        except Exception:
            row["PriceMove"] = pd.NA
        rows.append(row)

    current = pd.DataFrame(rows)
    if not current.empty:
        current = current.sort_values(["SportTitle", "MarketKey", "Outcome", "Book"]).reset_index(drop=True)
    current.to_csv(CURRENT_OUTPUT, index=False)
    print(f"Tracked futures movement snapshot at {HISTORY_OUTPUT}")
    print(f"Updated futures movement summary at {CURRENT_OUTPUT}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch futures/outrights odds from The Odds API")
    parser.add_argument("--api-key", help="The Odds API key. Prefer ODDS_API_KEY env var.")
    parser.add_argument("--sports", help="Comma-separated sport keys. Defaults to active football/basketball/baseball futures.")
    parser.add_argument("--bookmakers", default=DEFAULT_BOOKMAKERS, help="Comma-separated bookmaker keys.")
    parser.add_argument("--regions", default=DEFAULT_REGIONS, help="Comma-separated region keys.")
    parser.add_argument("--include-inactive", action="store_true", help="Include inactive sports in the futures catalog and default fetch set.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Latest futures odds CSV path.")
    parser.add_argument("--sports-output", default=str(DEFAULT_SPORTS_OUTPUT), help="Futures sports catalog CSV path.")
    parser.add_argument("--skip-movement", action="store_true", help="Do not append rows to futures movement tracking files.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_key = get_api_key(args.api_key)
    sports = fetch_sports(api_key, include_inactive=True)
    outright_sports = select_outright_sports(sports, DEFAULT_GROUPS, include_inactive=args.include_inactive)
    write_sports_catalog(outright_sports, Path(args.sports_output).expanduser().resolve())

    if args.sports:
        wanted = {item.strip() for item in args.sports.split(",") if item.strip()}
        selected = [sport for sport in sports if sport.get("key") in wanted]
    else:
        selected = outright_sports

    print("=" * 60)
    print("BANKROLL KINGS - Fetch Futures Odds")
    print("=" * 60)
    print(f"Sports: {', '.join(s.get('key', '') for s in selected) or 'none'}")
    print(f"Bookmakers: {args.bookmakers}")
    print(f"Regions: {args.regions}")
    print()

    all_rows: list[dict] = []
    failures: list[str] = []
    for sport in selected:
        key = sport.get("key", "")
        try:
            rows = fetch_outright_rows(api_key, sport, args.bookmakers, args.regions)
            all_rows.extend(rows)
            print(f"{key}: {len(rows)} rows")
        except Exception as exc:
            failures.append(f"{key}: {exc}")
            print(f"{key}: ERROR {exc}")

    df = build_dataframe(all_rows)
    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if df.empty and output_path.exists():
        print("No futures rows fetched. Preserving existing latest futures file.")
    else:
        df.to_csv(output_path, index=False)
        if not args.skip_movement:
            append_futures_movement_snapshot(df)

    print()
    print(f"Saved {len(df)} latest futures rows to {output_path}")
    print(f"Wrote futures sports catalog to {Path(args.sports_output).expanduser().resolve()}")
    if failures:
        print("Failures:")
        for failure in failures:
            print(f"  - {failure}")
        return 1 if df.empty else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
