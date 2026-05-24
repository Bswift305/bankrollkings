from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SCHEDULE_PATH = DATA_DIR / "schedules" / "MLB_Schedule.csv"
ODDS_PATH = DATA_DIR / "odds" / "MLB_Odds.csv"
FACTORS_PATH = DATA_DIR / "context" / "MLB_BallparkFactors.csv"
CONTEXT_PATH = DATA_DIR / "context" / "MLB_GameContext.csv"

CONTEXT_COLUMNS = [
    "Date", "Away", "Home", "Ballpark", "ParkHRFactor", "Temperature",
    "WindMph", "WindDirection", "Umpire", "UmpireZone", "Source", "LastUpdated",
]


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def _clean_team(value) -> str:
    return str(value or "").strip()


def _manual_context_lookup(existing: pd.DataFrame) -> dict:
    if existing.empty:
        return {}
    lookup = {}
    for _, row in existing.iterrows():
        key = (str(row.get("Date") or "").strip(), _clean_team(row.get("Away")), _clean_team(row.get("Home")))
        lookup[key] = row.to_dict()
    return lookup


def build_context() -> pd.DataFrame:
    schedule = _read_csv(SCHEDULE_PATH)
    odds = _read_csv(ODDS_PATH)
    factors = _read_csv(FACTORS_PATH)
    existing = _read_csv(CONTEXT_PATH)
    if schedule.empty and odds.empty:
        return pd.DataFrame(columns=CONTEXT_COLUMNS)

    source = schedule if not schedule.empty else odds
    source = source.copy()
    for col in ["Date", "Away", "Home", "AwayFull", "HomeFull"]:
        if col not in source.columns:
            source[col] = ""
        source[col] = source[col].fillna("").astype(str).str.strip()

    factors_lookup = {}
    if not factors.empty:
        for _, row in factors.iterrows():
            team = _clean_team(row.get("Team"))
            if team:
                factors_lookup[team] = row.to_dict()

    manual_lookup = _manual_context_lookup(existing)
    rows = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    seen = set()
    for _, game in source.iterrows():
        date = str(game.get("Date") or "").strip()
        away = _clean_team(game.get("AwayFull") or game.get("Away"))
        home = _clean_team(game.get("HomeFull") or game.get("Home"))
        if not date or not away or not home:
            continue
        key = (date, away, home)
        if key in seen:
            continue
        seen.add(key)
        factor = factors_lookup.get(home, {})
        manual = manual_lookup.get(key, {})
        rows.append({
            "Date": date,
            "Away": away,
            "Home": home,
            "Ballpark": str(manual.get("Ballpark") or factor.get("Ballpark") or "").strip(),
            "ParkHRFactor": manual.get("ParkHRFactor") if pd.notna(manual.get("ParkHRFactor", pd.NA)) else factor.get("ParkHRFactor", ""),
            "Temperature": manual.get("Temperature", ""),
            "WindMph": manual.get("WindMph", ""),
            "WindDirection": manual.get("WindDirection", ""),
            "Umpire": manual.get("Umpire", ""),
            "UmpireZone": manual.get("UmpireZone", ""),
            "Source": "ballpark_static" if not manual.get("Source") else str(manual.get("Source")),
            "LastUpdated": now,
        })

    return pd.DataFrame(rows, columns=CONTEXT_COLUMNS)


def main() -> int:
    context = build_context()
    CONTEXT_PATH.parent.mkdir(parents=True, exist_ok=True)
    context.to_csv(CONTEXT_PATH, index=False)
    missing_ballparks = int((context["Ballpark"].fillna("").astype(str).str.strip() == "").sum()) if not context.empty else 0
    missing_weather = int((context["Temperature"].fillna("").astype(str).str.strip() == "").sum()) if not context.empty else 0
    missing_umpires = int((context["Umpire"].fillna("").astype(str).str.strip() == "").sum()) if not context.empty else 0
    print("=" * 60)
    print("BANKROLL KINGS - MLB GAME CONTEXT")
    print("=" * 60)
    print(f"Rows written: {len(context)}")
    print(f"Missing ballparks: {missing_ballparks}")
    print(f"Missing weather: {missing_weather}")
    print(f"Missing umpires: {missing_umpires}")
    print(f"Output: {CONTEXT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
