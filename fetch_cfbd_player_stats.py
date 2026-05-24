from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from app import _format_ncaaf_player_stats_history


BASE_DIR = Path(__file__).parent.resolve()
OUTPUT_PATH = BASE_DIR / "data" / "historical" / "NCAAF_PlayerStats_History.csv"
BASE_URL = "https://api.collegefootballdata.com"
DEFAULT_CATEGORIES = ["passing", "rushing", "receiving", "defensive"]


def get_api_key(cli_value: str | None) -> str:
    api_key = (
        cli_value
        or os.getenv("CFBD_API_KEY")
        or os.getenv("COLLEGEFOOTBALLDATA_API_KEY")
    )
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


def _coalesce(record: dict, *keys: str) -> Any:
    for key in keys:
        if key in record and record[key] not in [None, ""]:
            return record[key]
    return ""


def _player_name(record: dict) -> str:
    full = _coalesce(record, "player", "name", "fullName")
    if full:
        return str(full).strip()
    first = str(_coalesce(record, "firstName", "first_name")).strip()
    last = str(_coalesce(record, "lastName", "last_name")).strip()
    return " ".join(part for part in [first, last] if part).strip()


def _parse_float(value: Any) -> float:
    try:
        if value in [None, ""]:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


STAT_FIELD_MAP = {
    "passing": {
        "YDS": "PassYds",
        "TD": "PassTD",
        "INT": "PassInt",
    },
    "rushing": {
        "YDS": "RushYds",
        "TD": "RushTD",
    },
    "receiving": {
        "REC": "Receptions",
        "YDS": "RecYds",
        "TD": "RecTD",
    },
    "defensive": {
        "TOT": "Tackles",
        "SOLO": "Tackles",
        "SACK": "Sacks",
        "INT": "DefInt",
    },
}


def normalize_stat_type(value: Any) -> str:
    cleaned = str(value or "").upper().strip()
    cleaned = cleaned.replace(" ", "").replace("/", "").replace(".", "")
    aliases = {
        "YARDS": "YDS",
        "PASSYDS": "YDS",
        "RUSHYDS": "YDS",
        "RECYDS": "YDS",
        "PASSINT": "INT",
        "INTS": "INT",
        "TDS": "TD",
        "RECEPTIONS": "REC",
        "CATCHES": "REC",
        "TOTTACKLES": "TOT",
        "TACKLES": "TOT",
        "SACKS": "SACK",
    }
    return aliases.get(cleaned, cleaned)


def fetch_category_rows(api_key: str, year: int, category: str) -> list[dict]:
    payload = get_json("/stats/player/season", api_key, year=year, category=category)
    return payload if isinstance(payload, list) else []


def build_export(api_key: str, year: int, categories: list[str]) -> pd.DataFrame:
    players: dict[tuple[str, str, str], dict[str, Any]] = {}

    for category in categories:
        rows = fetch_category_rows(api_key, year, category)
        field_map = STAT_FIELD_MAP.get(category, {})
        for row in rows:
            player = _player_name(row)
            team = str(_coalesce(row, "team", "school")).strip()
            position = str(_coalesce(row, "position", "pos")).strip()
            if not player or not team:
                continue

            player_id = str(_coalesce(row, "playerId", "id", "athleteId")).strip()
            key = (player_id, player, team)
            record = players.setdefault(
                key,
                {
                    "PlayerID": player_id,
                    "Player": player,
                    "Team": team,
                    "Position": position,
                    "Class": str(_coalesce(row, "year", "class", "classification")).strip(),
                    "Season": year,
                    "Games": _parse_float(_coalesce(row, "games", "gp")),
                    "PassYds": 0.0,
                    "PassTD": 0.0,
                    "PassInt": 0.0,
                    "RushYds": 0.0,
                    "RushTD": 0.0,
                    "Receptions": 0.0,
                    "RecYds": 0.0,
                    "RecTD": 0.0,
                    "Tackles": 0.0,
                    "Sacks": 0.0,
                    "DefInt": 0.0,
                },
            )

            stat_type = normalize_stat_type(_coalesce(row, "statType", "stat_type", "stat"))
            target_field = field_map.get(stat_type)
            stat_value = _parse_float(_coalesce(row, "stat", "value"))

            if target_field:
                if category == "defensive" and target_field == "Tackles" and stat_type == "SOLO":
                    record[target_field] = max(record[target_field], stat_value)
                else:
                    record[target_field] += stat_value

            record["Games"] = max(record["Games"], _parse_float(_coalesce(row, "games", "gp")))
            if not record["Position"]:
                record["Position"] = position
            if not record["Class"]:
                record["Class"] = str(_coalesce(row, "year", "class", "classification")).strip()

    return pd.DataFrame(players.values())


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch CFB player season stats from CollegeFootballData.")
    parser.add_argument("--year", type=int, default=2025, help="Season year to fetch")
    parser.add_argument("--categories", default=",".join(DEFAULT_CATEGORIES), help="Comma-separated CFBD stat categories")
    parser.add_argument("--api-key", default=None, help="CFBD API key (falls back to CFBD_API_KEY)")
    parser.add_argument("--output", default=str(OUTPUT_PATH), help="Output CSV path")
    args = parser.parse_args()

    api_key = get_api_key(args.api_key)
    categories = [item.strip().lower() for item in args.categories.split(",") if item.strip()]

    raw = build_export(api_key, args.year, categories)
    formatted = _format_ncaaf_player_stats_history(raw)
    export = formatted[
        [
            "PlayerID",
            "Player",
            "Team",
            "Position",
            "Class",
            "Season",
            "Games",
            "PassYds",
            "PassTD",
            "PassInt",
            "RushYds",
            "RushTD",
            "Receptions",
            "RecYds",
            "RecTD",
            "Tackles",
            "Sacks",
            "DefInt",
        ]
    ].copy()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    export.to_csv(output_path, index=False)
    print(f"Wrote {len(export)} rows for {args.year} to {output_path}")


if __name__ == "__main__":
    main()
