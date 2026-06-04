from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SCHEDULE_PATH = DATA_DIR / "schedules" / "MLB_Schedule.csv"
ASSIGNMENTS_PATH = DATA_DIR / "context" / "MLB_UmpireAssignments.csv"
PROFILES_PATH = DATA_DIR / "context" / "MLB_UmpireProfiles.csv"
SOURCE_URL = "https://www.refmetrics.com/baseball/mlb/umpire-assignments"

ASSIGNMENT_COLUMNS = [
    "Date",
    "Away",
    "Home",
    "Umpire",
    "UmpireZone",
    "KImpact",
    "RunImpact",
    "UmpireSource",
    "AssignmentStatus",
    "LastUpdated",
]


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def clean_text(value) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split()).strip()


def team_key(value) -> str:
    return " ".join(str(value or "").strip().upper().split())


def schedule_lookup() -> dict[tuple[str, str], dict]:
    schedule = read_csv(SCHEDULE_PATH)
    lookup: dict[tuple[str, str], dict] = {}
    if schedule.empty:
        return lookup
    working = schedule.copy()
    for col in ["Date", "Away", "Home", "AwayFull", "HomeFull"]:
        if col not in working.columns:
            working[col] = ""
        working[col] = working[col].fillna("").astype(str).str.strip()
    for _, row in working.iterrows():
        away = str(row.get("AwayFull") or row.get("Away") or "").strip()
        home = str(row.get("HomeFull") or row.get("Home") or "").strip()
        date = str(row.get("Date") or "").strip()
        if away and home and date:
            lookup[(team_key(home), team_key(away))] = {"Date": date, "Away": away, "Home": home}
    return lookup


def profile_lookup() -> dict[str, dict]:
    profiles = read_csv(PROFILES_PATH)
    lookup = {}
    if profiles.empty:
        return lookup
    for _, row in profiles.iterrows():
        umpire = clean_text(row.get("Umpire")).lower()
        if umpire:
            lookup[umpire] = row.to_dict()
    return lookup


def existing_lookup() -> dict[tuple[str, str, str], dict]:
    existing = read_csv(ASSIGNMENTS_PATH)
    lookup = {}
    if existing.empty:
        return lookup
    for _, row in existing.iterrows():
        date = clean_text(row.get("Date"))
        away = clean_text(row.get("Away"))
        home = clean_text(row.get("Home"))
        if date and away and home:
            lookup[(date, team_key(away), team_key(home))] = row.to_dict()
    return lookup


def fetch_html() -> str:
    response = requests.get(
        SOURCE_URL,
        headers={"User-Agent": "BankrollKings/1.0 (+local analytics pipeline)"},
        timeout=25,
    )
    response.raise_for_status()
    return response.text


def parse_refmetrics_rows(raw_html: str) -> list[dict]:
    marker = '<table class="mlb-table mlb-today-table"'
    start = raw_html.find(marker)
    if start < 0:
        return []
    end = raw_html.find("</table>", start)
    if end < 0:
        return []
    table_html = raw_html[start:end]
    rows = []
    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, flags=re.I | re.S):
        cells = [clean_text(cell) for cell in re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.I | re.S)]
        if len(cells) < 8:
            continue
        rows.append({
            "Time": cells[0],
            "Home": cells[1],
            "Away": cells[2],
            "Umpire": cells[3],
            "FirstBase": cells[4],
            "SecondBase": cells[5],
            "ThirdBase": cells[6],
            "Status": cells[7],
        })
    return rows


def build_assignments() -> pd.DataFrame:
    games = schedule_lookup()
    profiles = profile_lookup()
    existing = existing_lookup()
    source_rows = parse_refmetrics_rows(fetch_html())
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    output_rows = []
    for source in source_rows:
        home_key = team_key(source.get("Home"))
        away_key = team_key(source.get("Away"))
        game = games.get((home_key, away_key), {})
        date = str(game.get("Date") or datetime.now().strftime("%Y-%m-%d"))
        away = str(game.get("Away") or source.get("Away") or "").strip()
        home = str(game.get("Home") or source.get("Home") or "").strip()
        umpire = clean_text(source.get("Umpire"))
        prior = existing.get((date, team_key(away), team_key(home)), {})
        profile = profiles.get(umpire.lower(), {}) if umpire else {}
        zone = clean_text(prior.get("UmpireZone") or profile.get("UmpireZone")).upper()
        output_rows.append({
            "Date": date,
            "Away": away,
            "Home": home,
            "Umpire": umpire,
            "UmpireZone": zone,
            "KImpact": prior.get("KImpact") or profile.get("KImpact") or "",
            "RunImpact": prior.get("RunImpact") or profile.get("RunImpact") or "",
            "UmpireSource": "refmetrics",
            "AssignmentStatus": "CONFIRMED" if umpire else "NEEDS_ASSIGNMENT",
            "LastUpdated": now,
        })
    return pd.DataFrame(output_rows, columns=ASSIGNMENT_COLUMNS)


def main() -> int:
    ASSIGNMENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        assignments = build_assignments()
    except Exception as exc:
        print("=" * 60)
        print("BANKROLL KINGS - MLB UMPIRE ASSIGNMENT FETCH")
        print("=" * 60)
        print(f"Fetch skipped: {type(exc).__name__}: {exc}")
        print("Existing assignment sidecar preserved.")
        return 0

    if assignments.empty:
        print("=" * 60)
        print("BANKROLL KINGS - MLB UMPIRE ASSIGNMENT FETCH")
        print("=" * 60)
        print("No assignment rows parsed. Existing assignment sidecar preserved.")
        return 0

    assignments.to_csv(ASSIGNMENTS_PATH, index=False)
    confirmed = int(assignments["Umpire"].fillna("").astype(str).str.strip().ne("").sum())
    print("=" * 60)
    print("BANKROLL KINGS - MLB UMPIRE ASSIGNMENT FETCH")
    print("=" * 60)
    print(f"Rows written: {len(assignments)}")
    print(f"Confirmed home plate umpires: {confirmed}")
    print(f"Source: {SOURCE_URL}")
    print(f"Output: {ASSIGNMENTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
