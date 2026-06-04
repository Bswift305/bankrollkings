from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SCHEDULE_PATH = DATA_DIR / "schedules" / "MLB_Schedule.csv"
ASSIGNMENTS_PATH = DATA_DIR / "context" / "MLB_UmpireAssignments.csv"
PROFILES_PATH = DATA_DIR / "context" / "MLB_UmpireProfiles.csv"

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

PROFILE_COLUMNS = [
    "Umpire",
    "UmpireZone",
    "KImpact",
    "RunImpact",
    "ProfileSource",
    "LastReviewed",
]


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def _clean(value) -> str:
    text = str(value or "").strip()
    return "" if text.lower() == "nan" else text


def _first_present(*values):
    for value in values:
        text = _clean(value)
        if text:
            return value
    return ""


def _normalize_assignments(assignments: pd.DataFrame) -> pd.DataFrame:
    if assignments.empty:
        assignments = pd.DataFrame(columns=ASSIGNMENT_COLUMNS)
    assignments = assignments.copy()
    for col in ASSIGNMENT_COLUMNS:
        if col not in assignments.columns:
            assignments[col] = ""
    for col in ["Date", "Away", "Home", "Umpire", "UmpireZone", "UmpireSource", "AssignmentStatus", "LastUpdated"]:
        assignments[col] = assignments[col].fillna("").astype(str).str.strip()
    return assignments[ASSIGNMENT_COLUMNS]


def _normalize_profiles(profiles: pd.DataFrame) -> pd.DataFrame:
    if profiles.empty:
        profiles = pd.DataFrame(columns=PROFILE_COLUMNS)
    profiles = profiles.copy()
    for col in PROFILE_COLUMNS:
        if col not in profiles.columns:
            profiles[col] = ""
    for col in ["Umpire", "UmpireZone", "ProfileSource", "LastReviewed"]:
        profiles[col] = profiles[col].fillna("").astype(str).str.strip()
    return profiles[PROFILE_COLUMNS]


def _schedule_games(schedule: pd.DataFrame) -> pd.DataFrame:
    if schedule.empty:
        return pd.DataFrame(columns=["Date", "Away", "Home"])
    source = schedule.copy()
    for col in ["Date", "Away", "Home", "AwayFull", "HomeFull"]:
        if col not in source.columns:
            source[col] = ""
        source[col] = source[col].fillna("").astype(str).str.strip()

    rows = []
    seen = set()
    for _, game in source.iterrows():
        date = _clean(game.get("Date"))
        away = _clean(game.get("AwayFull")) or _clean(game.get("Away"))
        home = _clean(game.get("HomeFull")) or _clean(game.get("Home"))
        key = (date, away, home)
        if not date or not away or not home or key in seen:
            continue
        seen.add(key)
        rows.append({"Date": date, "Away": away, "Home": home})
    return pd.DataFrame(rows, columns=["Date", "Away", "Home"])


def build_umpire_context() -> pd.DataFrame:
    schedule = _schedule_games(_read_csv(SCHEDULE_PATH))
    assignments = _normalize_assignments(_read_csv(ASSIGNMENTS_PATH))
    profiles = _normalize_profiles(_read_csv(PROFILES_PATH))

    profile_lookup = {}
    for _, row in profiles.iterrows():
        umpire = _clean(row.get("Umpire")).lower()
        if umpire:
            profile_lookup[umpire] = row.to_dict()

    assignment_lookup = {}
    for _, row in assignments.iterrows():
        key = (_clean(row.get("Date")), _clean(row.get("Away")), _clean(row.get("Home")))
        if key[0] and key[1] and key[2]:
            assignment_lookup[key] = row.to_dict()

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = []
    for _, game in schedule.iterrows():
        key = (_clean(game.get("Date")), _clean(game.get("Away")), _clean(game.get("Home")))
        existing = assignment_lookup.get(key, {})
        umpire = _clean(existing.get("Umpire"))
        profile = profile_lookup.get(umpire.lower(), {}) if umpire else {}
        zone = str(_first_present(existing.get("UmpireZone"), profile.get("UmpireZone"))).strip().upper()
        status = "CONFIRMED" if umpire else "NEEDS_ASSIGNMENT"
        rows.append({
            "Date": key[0],
            "Away": key[1],
            "Home": key[2],
            "Umpire": umpire,
            "UmpireZone": zone,
            "KImpact": _first_present(existing.get("KImpact"), profile.get("KImpact")),
            "RunImpact": _first_present(existing.get("RunImpact"), profile.get("RunImpact")),
            "UmpireSource": _first_present(existing.get("UmpireSource"), profile.get("ProfileSource"), "manual_sidecar"),
            "AssignmentStatus": status,
            "LastUpdated": now,
        })

    out = pd.DataFrame(rows, columns=ASSIGNMENT_COLUMNS)
    if out.empty:
        out = pd.DataFrame(columns=ASSIGNMENT_COLUMNS)
    return out


def main() -> int:
    ASSIGNMENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    profiles = _normalize_profiles(_read_csv(PROFILES_PATH))
    if not PROFILES_PATH.exists():
        profiles.to_csv(PROFILES_PATH, index=False)

    assignments = build_umpire_context()
    assignments.to_csv(ASSIGNMENTS_PATH, index=False)
    confirmed = int(assignments["Umpire"].fillna("").astype(str).str.strip().ne("").sum()) if not assignments.empty else 0
    needs = int((assignments["AssignmentStatus"].astype(str) == "NEEDS_ASSIGNMENT").sum()) if not assignments.empty else 0
    print("=" * 60)
    print("BANKROLL KINGS - MLB UMPIRE CONTEXT")
    print("=" * 60)
    print(f"Rows written: {len(assignments)}")
    print(f"Confirmed umpires: {confirmed}")
    print(f"Needs assignment: {needs}")
    print(f"Assignments: {ASSIGNMENTS_PATH}")
    print(f"Profiles: {PROFILES_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
