from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from services.env_loader import load_local_env


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_TEMPLATE = BASE_DIR / "data" / "historical" / "NCAAF_CFBD_Games_{year}.csv"


def _api_key(cli_value: str | None = None) -> str:
    load_local_env(BASE_DIR)
    key = cli_value or os.getenv("CFBD_API_KEY")
    if not key:
        raise ValueError("Missing CFBD_API_KEY. Set it in .env.local or pass --api-key.")
    return key.strip()


def _get_json(path: str, api_key: str, **params) -> list[dict]:
    url = f"https://api.collegefootballdata.com{path}?{urlencode(params)}"
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "accept": "application/json",
            "User-Agent": "BankrollKings/1.0",
        },
    )
    with urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, list) else []


def fetch_games(year: int, api_key: str, season_types: list[str]) -> pd.DataFrame:
    rows: list[dict] = []
    for season_type in season_types:
        games = _get_json("/games", api_key, year=year, seasonType=season_type)
        print(f"[OK] {year} {season_type}: {len(games)} games")
        for game in games:
            rows.append(
                {
                    "GameID": game.get("id"),
                    "Season": game.get("season", year),
                    "Week": game.get("week"),
                    "SeasonType": game.get("seasonType", season_type),
                    "StartDate": game.get("startDate"),
                    "Date": str(game.get("startDate", ""))[:10],
                    "Away": game.get("awayTeam", ""),
                    "Home": game.get("homeTeam", ""),
                    "AwayScore": game.get("awayPoints"),
                    "HomeScore": game.get("homePoints"),
                    "Completed": bool(game.get("completed")),
                    "NeutralSite": bool(game.get("neutralSite")),
                    "ConferenceGame": bool(game.get("conferenceGame")),
                    "AwayConference": game.get("awayConference", ""),
                    "HomeConference": game.get("homeConference", ""),
                    "Venue": game.get("venue", ""),
                    "Source": "cfbd_games",
                }
            )
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(
            columns=[
                "GameID",
                "Season",
                "Week",
                "SeasonType",
                "StartDate",
                "Date",
                "Away",
                "Home",
                "AwayScore",
                "HomeScore",
                "Completed",
                "NeutralSite",
                "ConferenceGame",
                "AwayConference",
                "HomeConference",
                "Venue",
                "Source",
            ]
        )
    for col in ["GameID", "Season", "Week", "AwayScore", "HomeScore"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.sort_values(["Date", "Week", "Away", "Home"]).drop_duplicates(
        subset=["Season", "Week", "Away", "Home"], keep="last"
    )
    return df.reset_index(drop=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch completed CFB game scores from CFBD.")
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--api-key", default=None)
    parser.add_argument(
        "--season-types",
        default="regular,postseason",
        help="Comma-separated CFBD season types. Default: regular,postseason",
    )
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    season_types = [item.strip() for item in args.season_types.split(",") if item.strip()]
    api_key = _api_key(args.api_key)
    df = fetch_games(args.year, api_key, season_types)
    output = Path(args.output).resolve() if args.output else Path(str(OUTPUT_TEMPLATE).format(year=args.year))
    output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output, index=False)
    completed = int(df.get("Completed", pd.Series(dtype=bool)).fillna(False).sum()) if not df.empty else 0
    print(f"Wrote {len(df)} rows to {output}")
    print(f"Completed games: {completed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
