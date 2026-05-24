from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pandas as pd

from app import _format_ncaaf_current_roster


BASE_DIR = Path(__file__).parent.resolve()
OUTPUT_PATH = BASE_DIR / "data" / "rosters" / "NCAAF_CurrentRoster.csv"
BASE_URL = "https://api.collegefootballdata.com"


def get_api_key(cli_value: str | None) -> str:
    api_key = (
        cli_value
        or os.getenv("CFBD_API_KEY")
        or os.getenv("COLLEGEFOOTBALLDATA_API_KEY")
    )
    if not api_key:
        raise ValueError("Missing CFBD API key. Set CFBD_API_KEY or pass --api-key.")
    return api_key.strip()


def get_json(path: str, api_key: str, retries: int = 3, **params: Any) -> list[dict] | dict:
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
    attempt = 0
    while True:
        try:
            with urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 429 and attempt < retries:
                wait_seconds = 2 ** attempt
                time.sleep(wait_seconds)
                attempt += 1
                continue
            raise


def _coalesce(record: dict, *keys: str) -> Any:
    for key in keys:
        if key in record and record[key] not in [None, ""]:
            return record[key]
    return ""


def _player_name(record: dict) -> str:
    full = _coalesce(record, "name", "player", "fullName")
    if full:
        return str(full).strip()
    first = str(_coalesce(record, "firstName", "first_name")).strip()
    last = str(_coalesce(record, "lastName", "last_name")).strip()
    return " ".join(part for part in [first, last] if part).strip()


def _class_value(record: dict) -> str:
    raw = _coalesce(record, "year", "classification", "class")
    if raw in [None, ""]:
        return ""
    return str(raw).strip()


def _jersey_value(record: dict) -> str:
    raw = _coalesce(record, "jersey", "number")
    if raw in [None, ""]:
        return ""
    return str(raw).strip()


def fetch_fbs_teams(api_key: str, year: int) -> list[str]:
    payload = get_json("/teams/fbs", api_key, year=year)
    teams: list[str] = []
    for row in payload if isinstance(payload, list) else []:
        team_name = _coalesce(row, "school", "team", "name")
        if team_name:
            teams.append(str(team_name).strip())
    return sorted({team for team in teams if team})


def fetch_bulk_roster_rows(api_key: str, year: int) -> list[dict]:
    payload = get_json("/roster", api_key, year=year)
    rows: list[dict] = []
    for player in payload if isinstance(payload, list) else []:
        rows.append(
            {
                "PlayerID": _coalesce(player, "id", "playerId", "athleteId"),
                "Player": _player_name(player),
                "CurrentTeam": _coalesce(player, "team", "school", "teamName"),
                "Position": _coalesce(player, "position", "pos"),
                "Class": _class_value(player),
                "Height": _coalesce(player, "height"),
                "Weight": _coalesce(player, "weight"),
                "Jersey": _jersey_value(player),
                "Status": _coalesce(player, "status"),
            }
        )
    return rows


def fetch_roster_rows(api_key: str, year: int, teams: list[str]) -> list[dict]:
    rows: list[dict] = []
    for team in teams:
        payload = get_json("/roster", api_key, year=year, team=team)
        for player in payload if isinstance(payload, list) else []:
            rows.append(
                {
                    "PlayerID": _coalesce(player, "id", "playerId", "athleteId"),
                    "Player": _player_name(player),
                    "CurrentTeam": _coalesce(player, "team", "school", "teamName") or team,
                    "Position": _coalesce(player, "position", "pos"),
                    "Class": _class_value(player),
                    "Height": _coalesce(player, "height"),
                    "Weight": _coalesce(player, "weight"),
                    "Jersey": _jersey_value(player),
                    "Status": _coalesce(player, "status"),
                }
            )
    return rows


def fetch_with_fallback(api_key: str, year: int, teams: list[str], fallback_year: int | None) -> tuple[list[dict], int]:
    rows = fetch_roster_rows(api_key, year, teams) if teams else fetch_bulk_roster_rows(api_key, year)
    if rows or fallback_year in [None, year]:
        return rows, year
    fallback_rows = fetch_roster_rows(api_key, fallback_year, teams) if teams else fetch_bulk_roster_rows(api_key, fallback_year)
    return fallback_rows, fallback_year


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch current CFB rosters from CollegeFootballData.")
    parser.add_argument("--year", type=int, default=2026, help="Roster year to fetch")
    parser.add_argument("--fallback-year", type=int, default=2025, help="Fallback roster year if the target year is empty")
    parser.add_argument("--teams", default="", help="Optional comma-separated list of teams to limit the pull")
    parser.add_argument("--api-key", default=None, help="CFBD API key (falls back to CFBD_API_KEY)")
    parser.add_argument("--output", default=str(OUTPUT_PATH), help="Output CSV path")
    args = parser.parse_args()

    api_key = get_api_key(args.api_key)
    if args.teams.strip():
        teams = [team.strip() for team in args.teams.split(",") if team.strip()]
    else:
        teams = []

    raw_rows, source_year = fetch_with_fallback(api_key, args.year, teams, args.fallback_year)
    raw = pd.DataFrame(raw_rows)
    formatted = _format_ncaaf_current_roster(raw)
    export = formatted[["PlayerID", "Player", "CurrentTeam", "Position", "Class", "Height", "Weight", "Jersey", "Status"]].copy()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    export.to_csv(output_path, index=False)
    team_count = export["CurrentTeam"].replace("", pd.NA).dropna().nunique() if not export.empty else 0
    print(f"Wrote {len(export)} rows across {team_count} teams to {output_path} (source year {source_year})")


if __name__ == "__main__":
    main()
