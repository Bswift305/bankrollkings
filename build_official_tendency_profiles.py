from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CONTEXT_DIR = DATA_DIR / "context"
OUTPUT_PATH = CONTEXT_DIR / "Official_TendencyProfiles.csv"

SPORT_METRICS = {
    "NBA": [
        ("charges_per_game", "Charges / game", ["charge", "charging foul"]),
        ("offensive_fouls_per_game", "Offensive fouls / game", ["offensive foul"]),
        ("shooting_fouls_per_game", "Shooting fouls / game", ["shooting foul"]),
        ("personal_fouls_per_game", "Personal fouls / game", ["personal foul"]),
        ("technicals_per_game", "Technical fouls / game", ["technical foul"]),
        ("free_throw_trips_per_game", "Free-throw trips created / game", ["free throw", "shooting foul"]),
    ],
    "WNBA": [
        ("charges_per_game", "Charges / game", ["charge", "charging foul"]),
        ("offensive_fouls_per_game", "Offensive fouls / game", ["offensive foul"]),
        ("shooting_fouls_per_game", "Shooting fouls / game", ["shooting foul"]),
        ("personal_fouls_per_game", "Personal fouls / game", ["personal foul"]),
        ("technicals_per_game", "Technical fouls / game", ["technical foul"]),
        ("free_throw_trips_per_game", "Free-throw trips created / game", ["free throw", "shooting foul"]),
    ],
    "NCAAMB": [
        ("charges_per_game", "Charges / game", ["charge", "charging foul"]),
        ("offensive_fouls_per_game", "Offensive fouls / game", ["offensive foul"]),
        ("shooting_fouls_per_game", "Shooting fouls / game", ["shooting foul"]),
        ("personal_fouls_per_game", "Personal fouls / game", ["personal foul"]),
        ("bonus_pressure_per_game", "Bonus-pressure fouls / game", ["personal foul", "shooting foul"]),
    ],
    "NCAAWB": [
        ("charges_per_game", "Charges / game", ["charge", "charging foul"]),
        ("offensive_fouls_per_game", "Offensive fouls / game", ["offensive foul"]),
        ("shooting_fouls_per_game", "Shooting fouls / game", ["shooting foul"]),
        ("personal_fouls_per_game", "Personal fouls / game", ["personal foul"]),
        ("bonus_pressure_per_game", "Bonus-pressure fouls / game", ["personal foul", "shooting foul"]),
    ],
    "NFL": [
        ("accepted_penalties_per_game", "Accepted penalties / game", ["penalty"]),
        ("defensive_pi_per_game", "Defensive pass interference / game", ["defensive pass interference"]),
        ("offensive_holding_per_game", "Offensive holding / game", ["offensive holding"]),
        ("defensive_holding_per_game", "Defensive holding / game", ["defensive holding"]),
        ("roughing_passer_per_game", "Roughing passer / game", ["roughing the passer"]),
        ("false_starts_per_game", "False starts / game", ["false start"]),
    ],
    "NCAAF": [
        ("accepted_penalties_per_game", "Accepted penalties / game", ["penalty"]),
        ("defensive_pi_per_game", "Defensive pass interference / game", ["defensive pass interference"]),
        ("offensive_holding_per_game", "Offensive holding / game", ["offensive holding"]),
        ("defensive_holding_per_game", "Defensive holding / game", ["defensive holding"]),
        ("roughing_passer_per_game", "Roughing passer / game", ["roughing the passer"]),
        ("false_starts_per_game", "False starts / game", ["false start"]),
    ],
    "MLB": [
        ("called_strike_rate", "Called strike tendency", ["called strike"]),
        ("ball_rate", "Ball-call tendency", ["ball"]),
        ("walk_pressure_per_game", "Walk pressure / game", ["walk"]),
        ("strikeout_pressure_per_game", "Strikeout pressure / game", ["strikeout", "called strike"]),
        ("ejections_per_game", "Ejections / game", ["ejection", "ejected"]),
    ],
}

EVENT_FILE_CANDIDATES = {
    "NBA": ["NBA_PlayByPlay.csv", "NBA_PBP.csv", "NBA_Events.csv"],
    "WNBA": ["WNBA_PlayByPlay.csv", "WNBA_PBP.csv", "WNBA_Events.csv"],
    "NCAAMB": ["NCAAMB_PlayByPlay.csv", "CBB_PlayByPlay.csv", "NCAAMB_Events.csv"],
    "NCAAWB": ["NCAAWB_PlayByPlay.csv", "WCBB_PlayByPlay.csv", "NCAAWB_Events.csv"],
    "NFL": ["NFL_PlayByPlay.csv", "NFL_PBP.csv", "NFL_Events.csv"],
    "NCAAF": ["NCAAF_PlayByPlay.csv", "CFB_PlayByPlay.csv", "NCAAF_Events.csv"],
    "MLB": ["MLB_PlayByPlay.csv", "MLB_PBP.csv", "MLB_Events.csv"],
}

EVENT_DIRS = [
    DATA_DIR / "events",
    DATA_DIR / "pbp",
    DATA_DIR / "play_by_play",
    DATA_DIR / "historical",
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
    if text.lower() == "nan":
        return ""
    return text


def _find_event_file(sport: str) -> Path | None:
    for directory in EVENT_DIRS:
        for name in EVENT_FILE_CANDIDATES.get(sport, []):
            path = directory / name
            if path.exists():
                return path
    return None


def _first_existing_column(df: pd.DataFrame, candidates: list[str]) -> str:
    lookup = {str(col).lower(): col for col in df.columns}
    for candidate in candidates:
        found = lookup.get(candidate.lower())
        if found:
            return found
    return ""


def _game_key(row) -> str:
    date = _clean(row.get("Date") or row.get("GameDate") or row.get("gameday"))
    away = _clean(row.get("Away") or row.get("away_team") or row.get("AwayTeam"))
    home = _clean(row.get("Home") or row.get("home_team") or row.get("HomeTeam"))
    game_id = _clean(row.get("GameID") or row.get("Game_Id") or row.get("game_id"))
    if game_id:
        return game_id
    return re.sub(r"\s+", "", f"{date}:{away}@{home}".lower())


def _event_contains(text: str, needles: list[str]) -> bool:
    text = str(text or "").lower()
    return any(needle.lower() in text for needle in needles)


def _load_assignments() -> pd.DataFrame:
    context = _read_csv(CONTEXT_DIR / "OfficiatingContext.csv")
    if context.empty:
        return pd.DataFrame(columns=["Sport", "Official", "Crew"])
    for col in ["Sport", "Official", "Crew", "Date", "Away", "Home", "AssignmentStatus", "ImpactMarkets", "ContextNote", "Source"]:
        if col not in context.columns:
            context[col] = ""
    context["GameKey"] = context.apply(_game_key, axis=1)
    return context


def _assignment_only_rows(assignments: pd.DataFrame, sport: str, now: str) -> list[dict]:
    sport_assignments = assignments[assignments["Sport"].astype(str).str.upper() == sport].copy()
    if sport_assignments.empty:
        officials = ["Pending Crew"]
        sample_games = 0
        impact_markets = ""
        note = "Assignment feed has not been loaded for this sport yet."
        source = "officiating_context"
    else:
        officials = sorted({
            _clean(value) or "Pending Crew"
            for value in sport_assignments.get("Official", pd.Series(dtype=str)).tolist()
        })
        sample_games = int(sport_assignments["GameKey"].nunique())
        impact_markets = _clean(sport_assignments.get("ImpactMarkets", pd.Series([""])).dropna().astype(str).iloc[0]) if not sport_assignments.empty else ""
        note = _clean(sport_assignments.get("ContextNote", pd.Series([""])).dropna().astype(str).iloc[0]) if not sport_assignments.empty else ""
        source = _clean(sport_assignments.get("Source", pd.Series([""])).dropna().astype(str).iloc[0]) if not sport_assignments.empty else "officiating_context"
    rows = []
    for official in officials:
        for metric_key, metric_label, _ in SPORT_METRICS[sport]:
            rows.append({
                "Sport": sport,
                "Official": official,
                "Crew": "",
                "MetricKey": metric_key,
                "MetricLabel": metric_label,
                "ValuePerGame": "",
                "SampleGames": sample_games if official != "Pending Crew" else 0,
                "SampleEvents": 0,
                "AttributionLevel": "ASSIGNMENT_ONLY" if official != "Pending Crew" else "NEEDS_ASSIGNMENT",
                "DataStatus": "NEEDS_EVENT_FEED",
                "ImpactMarkets": impact_markets,
                "ContextNote": note or "Event-level play-by-play is required before this tendency becomes a real per-game average.",
                "Source": source,
                "LastUpdated": now,
            })
    return rows


def _event_profile_rows(assignments: pd.DataFrame, sport: str, event_path: Path, now: str) -> list[dict]:
    events = _read_csv(event_path)
    if events.empty:
        return []
    desc_col = _first_existing_column(events, ["Description", "description", "desc", "PlayDescription", "play_description", "Event", "event", "details"])
    if not desc_col:
        return []
    official_col = _first_existing_column(events, ["Official", "official", "Referee", "referee", "Umpire", "umpire", "CallingOfficial", "calling_official"])
    game_col = _first_existing_column(events, ["GameID", "game_id", "GAME_ID", "Game_Id"])
    events = events.copy()
    events["_GameKey"] = events[game_col].astype(str) if game_col else events.apply(_game_key, axis=1)
    events["_Description"] = events[desc_col].fillna("").astype(str)

    attribution = "INDIVIDUAL_WHISTLE" if official_col else "CREW_GAME"
    if official_col:
        events["_Official"] = events[official_col].fillna("").astype(str).str.strip()
    else:
        assign_cols = ["GameKey", "Official", "Crew", "ImpactMarkets", "ContextNote", "Source"]
        sport_assignments = assignments[assignments["Sport"].astype(str).str.upper() == sport][assign_cols].copy()
        events = events.merge(sport_assignments, left_on="_GameKey", right_on="GameKey", how="left")
        events["_Official"] = events["Official"].fillna("").astype(str).str.strip()
    events.loc[events["_Official"].eq(""), "_Official"] = "Unknown Crew"
    total_games = events.groupby("_Official")["_GameKey"].nunique().to_dict()

    rows = []
    for official, group in events.groupby("_Official", dropna=False):
        official = _clean(official) or "Unknown Crew"
        games = int(total_games.get(official, 0))
        if games <= 0:
            continue
        for metric_key, metric_label, needles in SPORT_METRICS[sport]:
            sample_events = int(group["_Description"].map(lambda text: _event_contains(text, needles)).sum())
            value = round(sample_events / games, 3)
            rows.append({
                "Sport": sport,
                "Official": official,
                "Crew": "",
                "MetricKey": metric_key,
                "MetricLabel": metric_label,
                "ValuePerGame": value,
                "SampleGames": games,
                "SampleEvents": sample_events,
                "AttributionLevel": attribution,
                "DataStatus": "READY" if official != "Unknown Crew" else "NEEDS_ASSIGNMENT",
                "ImpactMarkets": "",
                "ContextNote": f"Calculated from {event_path.name}; attribution level: {attribution}.",
                "Source": str(event_path.relative_to(BASE_DIR)),
                "LastUpdated": now,
            })
    return rows


def build_official_tendency_profiles() -> pd.DataFrame:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    assignments = _load_assignments()
    rows = []
    for sport in SPORT_METRICS:
        event_path = _find_event_file(sport)
        event_rows = _event_profile_rows(assignments, sport, event_path, now) if event_path else []
        rows.extend(event_rows or _assignment_only_rows(assignments, sport, now))
    return pd.DataFrame(rows)


def main() -> int:
    CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
    profiles = build_official_tendency_profiles()
    profiles.to_csv(OUTPUT_PATH, index=False)
    ready = int((profiles["DataStatus"].astype(str).str.upper() == "READY").sum()) if not profiles.empty else 0
    event_feed = int((profiles["AttributionLevel"].astype(str).str.upper().isin(["INDIVIDUAL_WHISTLE", "CREW_GAME"])).sum()) if not profiles.empty else 0
    print("=" * 70)
    print("BANKROLL KINGS - OFFICIAL TENDENCY PROFILES")
    print("=" * 70)
    print(f"Rows written: {len(profiles)}")
    print(f"Ready tendency metrics: {ready}")
    print(f"Event-fed metric rows: {event_feed}")
    print(f"Output: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
