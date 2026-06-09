from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd

from services.timeutils import to_eastern_datetime_str


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_PATH = BASE_DIR / "data" / "schedules" / "MLB_Schedule.csv"
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_json(url: str) -> dict:
    with urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def build_url(path: str, **params) -> str:
    clean_params = {k: v for k, v in params.items() if v not in [None, ""]}
    return f"https://statsapi.mlb.com{path}?{urlencode(clean_params)}"


def fetch_schedule(start_date: str, end_date: str) -> list[dict]:
    url = build_url(
        "/api/v1/schedule",
        sportId=1,
        startDate=start_date,
        endDate=end_date,
        hydrate="linescore,team",
    )
    payload = get_json(url)
    rows: list[dict] = []
    for date_block in payload.get("dates", []):
        for game in date_block.get("games", []):
            teams = game.get("teams", {})
            away = teams.get("away", {}).get("team", {})
            home = teams.get("home", {}).get("team", {})
            game_dt = str(game.get("gameDate") or "")
            local_dt = ""
            if game_dt:
                # Fixed Eastern display, not the process's ambient zone.
                # See services.timeutils for why a bare .astimezone() is unsafe.
                local_dt = to_eastern_datetime_str(game_dt)
            date_text, time_text = ("", "")
            if local_dt:
                parts = local_dt.split(" ", 1)
                date_text = parts[0]
                time_text = parts[1] if len(parts) > 1 else ""
            rows.append({
                "Date": date_text or str(date_block.get("date") or ""),
                "Time": time_text,
                "Away": str(away.get("abbreviation") or "").strip(),
                "Home": str(home.get("abbreviation") or "").strip(),
                "AwayFull": str(away.get("name") or "").strip(),
                "HomeFull": str(home.get("name") or "").strip(),
                "GameID": game.get("gamePk"),
                "Status": str(game.get("status", {}).get("abstractGameState") or "").strip(),
                "DetailedState": str(game.get("status", {}).get("detailedState") or "").strip(),
            })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch MLB schedule from MLB Stats API")
    parser.add_argument("--days", type=int, default=14, help="Days forward to fetch.")
    parser.add_argument("--days-back", type=int, default=0, help="Days back to include.")
    args = parser.parse_args()

    today = datetime.now().date()
    start_date = (today - timedelta(days=max(args.days_back, 0))).isoformat()
    end_date = (today + timedelta(days=max(args.days, 0))).isoformat()

    print("=" * 60)
    print("BANKROLL KINGS - Refresh MLB Schedule")
    print("=" * 60)
    print(f"Window: {start_date} -> {end_date}")

    rows = fetch_schedule(start_date, end_date)
    df = pd.DataFrame(rows)
    if not df.empty:
        if {"Date", "Away", "Home"}.issubset(df.columns):
            df = df.drop_duplicates(subset=["Date", "Away", "Home"], keep="last").sort_values(["Date", "Time", "Away", "Home"])
    df.to_csv(OUTPUT_PATH, index=False)
    print(f"Saved {len(df)} MLB schedule rows to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
