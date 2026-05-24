from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from app import (
    _format_ncaaf_current_roster,
    load_ncaaf_returning_production,
    load_ncaaf_current_roster,
    normalize_ncaaf_team_name,
)


BASE_DIR = Path(__file__).parent.resolve()
OUTPUT_PATH = BASE_DIR / "data" / "rosters" / "NCAAF_CurrentRoster.csv"
REPORT_PATH = BASE_DIR / "data" / "tracking" / "NCAAF_CurrentRoster_Coverage.csv"
BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/football/college-football"


def get_json(url: str) -> list[dict] | dict:
    request = Request(
        url,
        headers={
            "User-Agent": "BankrollKings/1.0",
            "Accept": "application/json",
        },
    )
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def build_url(path: str, **params: Any) -> str:
    clean = {k: v for k, v in params.items() if v not in [None, ""]}
    url = f"{BASE_URL}{path}"
    if clean:
        url = f"{url}?{urlencode(clean)}"
    return url


def coalesce(record: dict, *keys: str) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in [None, ""]:
            return value
    return ""


def get_d1_team_universe() -> set[str]:
    teams: set[str] = set()
    roster = load_ncaaf_current_roster()
    if not roster.empty and "CurrentTeam" in roster.columns:
        teams.update(team for team in roster["CurrentTeam"].dropna().astype(str).str.strip() if team)
    returning = load_ncaaf_returning_production()
    if not returning.empty and "Team" in returning.columns:
        teams.update(team for team in returning["Team"].dropna().astype(str).str.strip() if team)
    return {normalize_ncaaf_team_name(team) for team in teams if normalize_ncaaf_team_name(team)}


def fetch_team_index(limit: int = 700) -> list[dict]:
    payload = get_json(build_url("/teams", limit=limit))
    teams: list[dict] = []
    for sport in payload.get("sports", []):
        for league in sport.get("leagues", []):
            for wrapper in league.get("teams", []):
                team = wrapper.get("team", {})
                team_name = normalize_ncaaf_team_name(coalesce(team, "location", "shortDisplayName", "displayName", "name"))
                if not team_name:
                    continue
                teams.append(
                    {
                        "TeamID": str(coalesce(team, "id")).strip(),
                        "Team": team_name,
                        "Abbreviation": str(coalesce(team, "abbreviation")).strip(),
                    }
                )
    unique: dict[str, dict] = {}
    for row in teams:
        unique[row["Team"]] = row
    return list(unique.values())


def eligible_teams(index_rows: list[dict], explicit_teams: list[str] | None = None) -> list[dict]:
    if explicit_teams:
        wanted = {normalize_ncaaf_team_name(team) for team in explicit_teams if normalize_ncaaf_team_name(team)}
        return [row for row in index_rows if row["Team"] in wanted]
    d1 = get_d1_team_universe()
    if not d1:
        return index_rows
    return [row for row in index_rows if row["Team"] in d1]


def parse_position(item: dict, group_name: str) -> str:
    position = item.get("position")
    if isinstance(position, dict):
        return str(coalesce(position, "abbreviation", "name", "displayName")).strip()
    if position not in [None, ""]:
        return str(position).strip()
    return group_name[:3].upper() if group_name else ""


def parse_class(item: dict) -> str:
    experience = item.get("experience")
    if isinstance(experience, dict):
        return str(coalesce(experience, "abbreviation", "displayValue", "name")).strip()
    return str(coalesce(item, "year", "class")).strip()


def parse_status(item: dict) -> str:
    status = item.get("status")
    if isinstance(status, dict):
        return str(coalesce(status, "type", "name", "displayValue")).strip()
    return str(status or "").strip()


def parse_headshot(item: dict) -> str:
    headshot = item.get("headshot")
    if isinstance(headshot, dict):
        return str(coalesce(headshot, "href", "alt", "url")).strip()
    return ""


def parse_experience(item: dict) -> tuple[str, str]:
    experience = item.get("experience")
    if isinstance(experience, dict):
        return (
            str(coalesce(experience, "abbreviation")).strip(),
            str(coalesce(experience, "displayValue", "name")).strip(),
        )
    raw = str(coalesce(item, "year", "class")).strip()
    return raw, raw


def fetch_team_roster(team_id: str, retries: int = 2) -> tuple[dict, list[dict]]:
    last_error = ""
    payload: dict | None = None
    for attempt in range(retries + 1):
        try:
            payload = get_json(build_url(f"/teams/{team_id}/roster"))
            break
        except Exception as exc:
            last_error = str(exc)
            if attempt >= retries:
                break
            time.sleep(0.5 * (attempt + 1))
    if payload is None:
        return (
            {
                "TeamID": str(team_id).strip(),
                "Team": "",
                "Abbreviation": "",
                "RosterRows": 0,
                "Status": "error",
                "Error": last_error[:240],
            },
            [],
        )
    team_info = payload.get("team", {})
    team_name = normalize_ncaaf_team_name(coalesce(team_info, "location", "shortDisplayName", "displayName", "name"))
    team_abbreviation = str(coalesce(team_info, "abbreviation")).strip()
    rows: list[dict] = []
    for group in payload.get("athletes", []):
        group_name = str(group.get("position", "")).strip()
        for item in group.get("items", []):
            class_abbrev, class_display = parse_experience(item)
            rows.append(
                {
                    "PlayerID": str(coalesce(item, "id")).strip(),
                    "ESPNPlayerID": str(coalesce(item, "id")).strip(),
                    "Player": str(coalesce(item, "fullName", "displayName")).strip(),
                    "FirstName": str(coalesce(item, "firstName")).strip(),
                    "LastName": str(coalesce(item, "lastName")).strip(),
                    "CurrentTeam": team_name,
                    "TeamID": str(team_id).strip(),
                    "TeamAbbreviation": team_abbreviation,
                    "Position": parse_position(item, group_name),
                    "PositionGroup": group_name,
                    "Class": class_abbrev or parse_class(item),
                    "ClassDisplay": class_display,
                    "Height": str(coalesce(item, "displayHeight", "height")).strip(),
                    "Weight": str(coalesce(item, "displayWeight", "weight")).strip(),
                    "Jersey": str(coalesce(item, "jersey")).strip(),
                    "Status": parse_status(item),
                    "Headshot": parse_headshot(item),
                }
            )
    summary = {
        "TeamID": str(team_id).strip(),
        "Team": team_name,
        "Abbreviation": team_abbreviation,
        "RosterRows": len(rows),
        "Status": "ok" if rows else "empty",
        "Error": "",
    }
    return summary, rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch current CFB rosters from ESPN and normalize for Bankroll Kings.")
    parser.add_argument("--teams", default="", help="Optional comma-separated list of teams to limit the pull")
    parser.add_argument("--limit", type=int, default=700, help="Team-index limit")
    parser.add_argument("--sleep-ms", type=int, default=75, help="Delay between roster calls in milliseconds")
    parser.add_argument("--output", default=str(OUTPUT_PATH), help="Output CSV path")
    parser.add_argument("--report", default=str(REPORT_PATH), help="Coverage report CSV path")
    parser.add_argument("--retries", type=int, default=2, help="Retry count per team roster request")
    args = parser.parse_args()

    explicit_teams = [team.strip() for team in args.teams.split(",") if team.strip()]
    index_rows = fetch_team_index(limit=args.limit)
    teams = eligible_teams(index_rows, explicit_teams)

    all_rows: list[dict] = []
    coverage_rows: list[dict] = []
    for idx, team in enumerate(teams, start=1):
        summary, rows = fetch_team_roster(team["TeamID"], retries=args.retries)
        all_rows.extend(rows)
        coverage_rows.append(
            {
                "RequestedTeam": team["Team"],
                "RequestedTeamID": team["TeamID"],
                "RequestedAbbreviation": team["Abbreviation"],
                "ResolvedTeam": summary.get("Team", ""),
                "ResolvedTeamID": summary.get("TeamID", ""),
                "ResolvedAbbreviation": summary.get("Abbreviation", ""),
                "RosterRows": summary.get("RosterRows", 0),
                "Status": summary.get("Status", ""),
                "Error": summary.get("Error", ""),
            }
        )
        if args.sleep_ms > 0 and idx < len(teams):
            time.sleep(args.sleep_ms / 1000)

    raw = pd.DataFrame(all_rows)
    formatted = _format_ncaaf_current_roster(raw)
    export = raw.copy()
    if not export.empty:
        export["CurrentTeam"] = export["CurrentTeam"].apply(normalize_ncaaf_team_name)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    export.to_csv(output_path, index=False)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(coverage_rows).to_csv(report_path, index=False)
    team_count = export["CurrentTeam"].replace("", pd.NA).dropna().nunique() if not export.empty else 0
    ok_count = sum(1 for row in coverage_rows if row["Status"] == "ok")
    empty_count = sum(1 for row in coverage_rows if row["Status"] == "empty")
    error_count = sum(1 for row in coverage_rows if row["Status"] == "error")
    print(f"Wrote {len(export)} rows across {team_count} teams to {output_path}")
    print(f"Coverage: ok={ok_count} empty={empty_count} error={error_count} report={report_path}")


if __name__ == "__main__":
    main()
