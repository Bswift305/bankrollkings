from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_PATH = BASE_DIR / "data" / "rosters" / "NFL_CurrentRoster.csv"
TEAM_SLUGS = [
    "ari", "atl", "bal", "buf", "car", "chi", "cin", "cle",
    "dal", "den", "det", "gb", "hou", "ind", "jax", "kc",
    "lv", "lac", "lar", "mia", "min", "ne", "no", "nyg",
    "nyj", "phi", "pit", "sea", "sf", "tb", "ten", "wsh",
]
TEAM_ABBR_ALIASES = {
    "JAC": "JAX",
    "WSH": "WAS",
    "WSN": "WAS",
    "LA": "LAR",
    "STL": "LAR",
    "SD": "LAC",
    "OAK": "LV",
}


def normalize_team_abbr(value: str) -> str:
    cleaned = str(value or "").strip().upper()
    return TEAM_ABBR_ALIASES.get(cleaned, cleaned)


def fetch_roster(slug: str, timeout: int) -> dict:
    url = f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{slug}/roster"
    request = urllib.request.Request(url, headers={"User-Agent": "BankrollKingsRosterRefresh/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def build_rows(timeout: int = 20, sleep_seconds: float = 0.05) -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    errors: list[str] = []
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for slug in TEAM_SLUGS:
        url = f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{slug}/roster"
        try:
            payload = fetch_roster(slug, timeout)
        except Exception as exc:
            errors.append(f"{slug}: {exc}")
            continue

        team = payload.get("team") or {}
        team_abbr = normalize_team_abbr(team.get("abbreviation") or slug.upper())
        team_name = team.get("displayName") or team.get("name") or team_abbr
        for group in payload.get("athletes") or []:
            for athlete in group.get("items") or []:
                player = athlete.get("displayName") or athlete.get("fullName") or athlete.get("shortName") or ""
                if not player:
                    continue
                position = athlete.get("position") or {}
                status = athlete.get("status") or {}
                rows.append({
                    "PlayerID": athlete.get("id") or "",
                    "Player": player,
                    "CurrentTeam": team_abbr,
                    "TeamName": team_name,
                    "Position": position.get("abbreviation") or position.get("name") or "",
                    "Jersey": athlete.get("jersey") or "",
                    "Status": status.get("name") or status.get("type") or "",
                    "LastUpdated": fetched_at,
                    "Source": url,
                })
        time.sleep(sleep_seconds)
    return rows, errors


def write_rows(rows: list[dict], output_path: Path = OUTPUT_PATH) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["PlayerID", "Player", "CurrentTeam", "TeamName", "Position", "Jersey", "Status", "LastUpdated", "Source"]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh current NFL rosters from ESPN team roster endpoints.")
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()

    rows, errors = build_rows(timeout=args.timeout)
    write_rows(rows)
    print(f"Saved {len(rows)} NFL roster rows to {OUTPUT_PATH}")
    if rows:
        print(f"Teams: {len({row['CurrentTeam'] for row in rows})}")
    if errors:
        print("Errors:")
        for error in errors:
            print(f"  - {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
