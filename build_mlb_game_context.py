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
WEATHER_PATH = DATA_DIR / "context" / "MLB_WeatherContext.csv"
UMPIRE_PATH = DATA_DIR / "context" / "MLB_UmpireAssignments.csv"

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


def _sidecar_lookup(df: pd.DataFrame) -> dict:
    if df.empty:
        return {}
    working = df.copy()
    for col in ["Date", "Away", "Home"]:
        if col not in working.columns:
            working[col] = ""
        working[col] = working[col].fillna("").astype(str).str.strip()
    lookup = {}
    for _, row in working.iterrows():
        key = (str(row.get("Date") or "").strip(), _clean_team(row.get("Away")), _clean_team(row.get("Home")))
        if key[0] and key[1] and key[2]:
            lookup[key] = row.to_dict()
    return lookup


def _first_present(*values):
    for value in values:
        if value is None:
            continue
        try:
            if pd.isna(value):
                continue
        except Exception:
            pass
        text = str(value).strip()
        if text and text.lower() != "nan":
            return value
    return ""


def build_context() -> pd.DataFrame:
    schedule = _read_csv(SCHEDULE_PATH)
    odds = _read_csv(ODDS_PATH)
    factors = _read_csv(FACTORS_PATH)
    existing = _read_csv(CONTEXT_PATH)
    weather = _read_csv(WEATHER_PATH)
    umpires = _read_csv(UMPIRE_PATH)
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
    weather_lookup = _sidecar_lookup(weather)
    umpire_lookup = _sidecar_lookup(umpires)
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
        weather_row = weather_lookup.get(key, {})
        umpire_row = umpire_lookup.get(key, {})
        source_bits = ["ballpark_static"] if factor else []
        if weather_row:
            source_bits.append(str(weather_row.get("WeatherSource") or "weather_sidecar").strip())
        if umpire_row:
            source_bits.append(str(umpire_row.get("UmpireSource") or "umpire_sidecar").strip())
        if manual.get("Source") and not weather_row and not umpire_row:
            source_bits = [str(manual.get("Source"))]
        rows.append({
            "Date": date,
            "Away": away,
            "Home": home,
            "Ballpark": str(manual.get("Ballpark") or factor.get("Ballpark") or "").strip(),
            "ParkHRFactor": _first_present(manual.get("ParkHRFactor"), factor.get("ParkHRFactor")),
            "Temperature": _first_present(weather_row.get("Temperature"), manual.get("Temperature")),
            "WindMph": _first_present(weather_row.get("WindMph"), manual.get("WindMph")),
            "WindDirection": _first_present(weather_row.get("WindDirection"), manual.get("WindDirection")),
            "Umpire": _first_present(umpire_row.get("Umpire"), manual.get("Umpire")),
            "UmpireZone": str(_first_present(umpire_row.get("UmpireZone"), manual.get("UmpireZone"))).upper(),
            "Source": "+".join([bit for bit in source_bits if bit]) or "context_builder",
            "LastUpdated": now,
        })

    return pd.DataFrame(rows, columns=CONTEXT_COLUMNS)


def main() -> int:
    context = build_context()
    CONTEXT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not WEATHER_PATH.exists():
        pd.DataFrame(columns=[
            "Date", "Away", "Home", "Temperature", "WindMph", "WindDirection",
            "WeatherSource", "LastUpdated",
        ]).to_csv(WEATHER_PATH, index=False)
    if not UMPIRE_PATH.exists():
        pd.DataFrame(columns=[
            "Date", "Away", "Home", "Umpire", "UmpireZone", "UmpireSource", "LastUpdated",
        ]).to_csv(UMPIRE_PATH, index=False)
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
