from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from app import _format_ncaaf_transfer_portal


BASE_DIR = Path(__file__).parent.resolve()
OUTPUT_PATH = BASE_DIR / "data" / "tracking" / "NCAAF_TransferPortal.csv"
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch CFB transfer portal data from CollegeFootballData.")
    parser.add_argument("--year", type=int, default=2026, help="Season year to fetch")
    parser.add_argument("--team", default="", help="Optional team filter")
    parser.add_argument("--api-key", default=None, help="CFBD API key (falls back to CFBD_API_KEY)")
    parser.add_argument("--output", default=str(OUTPUT_PATH), help="Output CSV path")
    args = parser.parse_args()

    api_key = get_api_key(args.api_key)
    payload = get_json("/player/portal", api_key, year=args.year, team=args.team)
    raw = pd.DataFrame(payload if isinstance(payload, list) else [])
    formatted = _format_ncaaf_transfer_portal(raw)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    formatted.to_csv(output_path, index=False)
    print(f"Wrote {len(formatted)} rows for {args.year} to {output_path}")


if __name__ == "__main__":
    main()
