from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from app import _format_ncaaf_returning_production


BASE_DIR = Path(__file__).parent.resolve()
OUTPUT_PATH = BASE_DIR / "data" / "tracking" / "NCAAF_ReturningProduction.csv"
BASE_URL = "https://api.collegefootballdata.com"


def get_api_key(cli_value: str | None) -> str:
    api_key = cli_value or os.getenv("CFBD_API_KEY") or os.getenv("COLLEGEFOOTBALLDATA_API_KEY")
    if not api_key:
        raise ValueError("Missing CFBD API key. Set CFBD_API_KEY or pass --api-key.")
    return api_key.strip()


def get_json(path: str, api_key: str, **params: Any) -> list[dict] | dict:
    query = {k: v for k, v in params.items() if v not in [None, ""]}
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


def fetch_with_fallback(api_key: str, year: int, team: str, fallback_year: int | None) -> tuple[list[dict] | dict, int]:
    payload = get_json("/player/returning", api_key, year=year, team=team)
    if (isinstance(payload, list) and payload) or fallback_year in [None, year]:
        return payload, year
    fallback_payload = get_json("/player/returning", api_key, year=fallback_year, team=team)
    return fallback_payload, fallback_year


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch CFB returning production from CollegeFootballData.")
    parser.add_argument("--year", type=int, default=2026, help="Season year to fetch")
    parser.add_argument("--fallback-year", type=int, default=2025, help="Fallback year if the target season is empty")
    parser.add_argument("--team", default="", help="Optional team filter")
    parser.add_argument("--api-key", default=None, help="CFBD API key (falls back to CFBD_API_KEY)")
    parser.add_argument("--output", default=str(OUTPUT_PATH), help="Output CSV path")
    args = parser.parse_args()

    api_key = get_api_key(args.api_key)
    payload, source_year = fetch_with_fallback(api_key, args.year, args.team, args.fallback_year)
    raw = pd.DataFrame(payload if isinstance(payload, list) else [])
    formatted = _format_ncaaf_returning_production(raw)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    formatted.to_csv(output_path, index=False)
    print(f"Wrote {len(formatted)} rows for {args.year} to {output_path} (source year {source_year})")


if __name__ == "__main__":
    main()
