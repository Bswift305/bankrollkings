from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from app import _format_ncaaf_game_lines_history
from services.env_loader import load_local_env


BASE_DIR = Path(__file__).parent.resolve()
BASE_URL = "https://api.collegefootballdata.com"
OUTPUT_PATH = BASE_DIR / "data" / "historical" / "NCAAF_GameLines_History.csv"


def get_api_key(cli_value: str | None) -> str:
    load_local_env(BASE_DIR)
    api_key = cli_value or os.getenv("CFBD_API_KEY") or os.getenv("COLLEGEFOOTBALLDATA_API_KEY")
    if not api_key:
        raise ValueError("Missing CFBD API key. Set CFBD_API_KEY or pass --api-key.")
    return api_key.strip()


def get_json(path: str, api_key: str, **params: Any) -> list[dict] | dict:
    query = {key: value for key, value in params.items() if value not in [None, ""]}
    url = f"{BASE_URL}{path}"
    if query:
        url = f"{url}?{urlencode(query)}"
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "BankrollKings/1.0",
        },
    )
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _num(value: Any) -> float | None:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return None
    return float(parsed)


def _first_line(row: dict, provider: str = "") -> dict:
    lines = row.get("lines") or []
    if not isinstance(lines, list) or not lines:
        return {}
    if provider:
        provider_clean = provider.lower().strip()
        for line in lines:
            line_provider = str(line.get("provider") or "").lower().strip()
            if line_provider == provider_clean:
                return line
    return lines[0]


def _home_spread(line: dict) -> float | None:
    for key in ("homeSpread", "home_spread", "spread"):
        value = _num(line.get(key))
        if value is not None:
            return value
    away_spread = _num(line.get("awaySpread") or line.get("away_spread"))
    if away_spread is not None:
        return -away_spread
    return None


def _away_spread(line: dict, home_spread: float | None) -> float | None:
    for key in ("awaySpread", "away_spread"):
        value = _num(line.get(key))
        if value is not None:
            return value
    if home_spread is not None:
        return -home_spread
    return None


def normalize_payload(payload: list[dict], season: int, provider: str = "") -> pd.DataFrame:
    rows: list[dict] = []
    for item in payload:
        line = _first_line(item, provider)
        if not line:
            continue
        home_spread = _home_spread(line)
        away_spread = _away_spread(line, home_spread)
        close_total = _num(line.get("overUnder") or line.get("total") or line.get("closeTotal"))
        open_total = _num(line.get("overUnderOpen") or line.get("openTotal"))
        rows.append({
            "Date": item.get("startDate") or item.get("start_date") or item.get("date"),
            "Season": item.get("season") or season,
            "Week": item.get("week"),
            "Away": item.get("awayTeam") or item.get("away_team"),
            "Home": item.get("homeTeam") or item.get("home_team"),
            "AwayScore": item.get("awayScore") if item.get("awayScore") is not None else item.get("away_score"),
            "HomeScore": item.get("homeScore") if item.get("homeScore") is not None else item.get("home_score"),
            "Spread": home_spread,
            "HomeSpread": home_spread,
            "AwaySpread": away_spread,
            "OpenHomeSpread": _num(line.get("homeSpreadOpen") or line.get("spreadOpen")),
            "OpenAwaySpread": _num(line.get("awaySpreadOpen")),
            "Total": close_total,
            "OpenTotal": open_total,
            "CloseTotal": close_total,
            "HomeCloseML": _num(line.get("homeMoneyline") or line.get("home_ml")),
            "AwayCloseML": _num(line.get("awayMoneyline") or line.get("away_ml")),
            "Source": f"cfbd:{line.get('provider') or provider or 'default'}",
        })
    if not rows:
        return pd.DataFrame()
    return _format_ncaaf_game_lines_history(pd.DataFrame(rows))


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch historical NCAAF game lines from CollegeFootballData.")
    parser.add_argument("--year", type=int, action="append", help="Season year to fetch. Repeat for multiple years.")
    parser.add_argument("--start-year", type=int, default=None, help="First season in a range.")
    parser.add_argument("--end-year", type=int, default=None, help="Last season in a range.")
    parser.add_argument("--season-type", default="regular", help="regular, postseason, or both if supported by CFBD.")
    parser.add_argument("--provider", default="", help="Optional CFBD line provider preference.")
    parser.add_argument("--api-key", default=None, help="CFBD API key. Prefer CFBD_API_KEY env var.")
    parser.add_argument("--output", default=str(OUTPUT_PATH), help="Output CSV path.")
    args = parser.parse_args()

    years = list(args.year or [])
    if args.start_year is not None and args.end_year is not None:
        years.extend(range(args.start_year, args.end_year + 1))
    years = sorted(set(years))
    if not years:
        raise SystemExit("Supply --year or --start-year/--end-year.")

    api_key = get_api_key(args.api_key)
    frames = []
    for year in years:
        payload = get_json("/lines", api_key, year=year, seasonType=args.season_type)
        frame = normalize_payload(payload if isinstance(payload, list) else [], year, args.provider)
        if not frame.empty:
            frames.append(frame)
        print(f"{year}: {len(frame)} line rows")

    output = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(output_path, index=False)
    print(f"Wrote {len(output)} rows to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
