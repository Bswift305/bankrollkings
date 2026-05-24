from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import os
import time

import pandas as pd
import requests


def _disable_dead_local_proxies() -> None:
    proxy_keys = [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ]
    for key in proxy_keys:
        value = os.environ.get(key, "")
        if value and "127.0.0.1:9" in value:
            os.environ.pop(key, None)


_disable_dead_local_proxies()

from nba_api.stats.endpoints import scoreboardv2
from nba_api.stats.static import teams


BASE_DIR = Path(__file__).resolve().parent
TRACKING_DIR = BASE_DIR / "data" / "tracking"
TRACKING_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_PATH = TRACKING_DIR / "NBA_Playoff_Results.csv"
PLAYOFF_GAMELOGS_PATH = BASE_DIR / "data" / "gamelogs" / "NBA_Playoff_GameLogs.csv"


SERIES_CONFIG = {
    "knicks-hawks": ("NYK", "ATL"),
    "cavaliers-raptors": ("CLE", "TOR"),
    "celtics-76ers": ("BOS", "PHI"),
    "pistons-magic": ("DET", "ORL"),
    "nuggets-timberwolves": ("DEN", "MIN"),
    "lakers-rockets": ("LAL", "HOU"),
    "thunder-suns": ("OKC", "PHX"),
    "spurs-trail-blazers": ("SAS", "POR"),
    "knicks-76ers": ("NYK", "PHI"),
    "pistons-cavaliers": ("DET", "CLE"),
    "spurs-timberwolves": ("SAS", "MIN"),
    "thunder-lakers": ("OKC", "LAL"),
    "cavaliers-knicks": ("CLE", "NYK"),
    "spurs-thunder": ("SAS", "OKC"),
    "warriors-clippers": ("GSW", "LAC"),
    "hornets-heat": ("CHA", "MIA"),
    "suns-clippers": ("PHX", "LAC"),
}

SERIES_LOOKUP = {frozenset(teams): series_id for series_id, teams in SERIES_CONFIG.items()}
TEAM_MAP = {t["id"]: t["abbreviation"] for t in teams.get_teams()}
ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
NBA_TEAM_ABBR_ALIASES = {
    "SA": "SAS",
    "GS": "GSW",
    "NO": "NOP",
    "NY": "NYK",
}


def infer_round(series_id: str) -> str:
    if series_id in {"warriors-clippers", "hornets-heat", "suns-clippers"}:
        return "Play-In"
    if series_id in {"knicks-76ers", "pistons-cavaliers", "spurs-timberwolves", "thunder-lakers"}:
        return "Conference Semifinals"
    if series_id in {"cavaliers-knicks", "spurs-thunder"}:
        return "Conference Finals"
    return "First Round"


def normalize_team_abbreviation(team: str) -> str:
    upper = str(team or "").strip().upper()
    return NBA_TEAM_ABBR_ALIASES.get(upper, upper)


def infer_game_number(series_rows: list[dict]) -> int:
    return len(series_rows) + 1


def build_recent_date_range(days_back: int = 14) -> list[str]:
    today = datetime.now().date()
    start = today - timedelta(days=days_back)
    return [(start + timedelta(days=offset)).strftime("%Y-%m-%d") for offset in range(days_back + 1)]


def is_final_game(game_row: pd.Series) -> bool:
    status_id = int(game_row.get("GAME_STATUS_ID", 0) or 0)
    status_text = str(game_row.get("GAME_STATUS_TEXT", "")).lower()
    return status_id == 3 or "final" in status_text


def fetch_postseason_results(days_back: int = 14) -> pd.DataFrame:
    rows: list[dict] = []
    by_series: dict[str, list[dict]] = {}

    for game_date in build_recent_date_range(days_back):
        try:
            board = scoreboardv2.ScoreboardV2(game_date=game_date)
            frames = board.get_data_frames()
            games_df = frames[0] if frames else pd.DataFrame()
            line_score_df = frames[1] if len(frames) > 1 else pd.DataFrame()
        except Exception as exc:
            print(f"Skipping {game_date}: {exc}")
            continue

        if games_df.empty:
            continue

        final_games = games_df[games_df.apply(is_final_game, axis=1)]
        if final_games.empty:
            continue

        for _, game in final_games.iterrows():
            away = TEAM_MAP.get(game.get("VISITOR_TEAM_ID"))
            home = TEAM_MAP.get(game.get("HOME_TEAM_ID"))
            if not away or not home:
                continue

            series_id = SERIES_LOOKUP.get(frozenset({away, home}))
            if not series_id:
                continue

            away_score = int(game.get("PTS_VISITOR", 0) or 0)
            home_score = int(game.get("PTS_HOME", 0) or 0)
            game_id = game.get("GAME_ID")

            if (away_score == 0 and home_score == 0) and not line_score_df.empty and game_id is not None:
                score_rows = line_score_df[line_score_df["GAME_ID"] == game_id].copy()
                if not score_rows.empty and {"TEAM_ID", "PTS"}.issubset(score_rows.columns):
                    away_team_id = game.get("VISITOR_TEAM_ID")
                    home_team_id = game.get("HOME_TEAM_ID")
                    away_line = score_rows[score_rows["TEAM_ID"] == away_team_id]
                    home_line = score_rows[score_rows["TEAM_ID"] == home_team_id]
                    if not away_line.empty:
                        away_score = int(float(away_line.iloc[0].get("PTS", 0) or 0))
                    if not home_line.empty:
                        home_score = int(float(home_line.iloc[0].get("PTS", 0) or 0))

            series_rows = by_series.setdefault(series_id, [])
            row = {
                "Date": game_date,
                "Away": away,
                "Home": home,
                "AwayScore": away_score,
                "HomeScore": home_score,
                "SeriesId": series_id,
                "Round": infer_round(series_id),
                "GameNumber": infer_game_number(series_rows),
            }
            series_rows.append(row)
            rows.append(row)

        time.sleep(0.7)

    if not rows:
        return pd.DataFrame(columns=["Date", "Away", "Home", "AwayScore", "HomeScore", "SeriesId", "Round", "GameNumber"])

    df = pd.DataFrame(rows).sort_values(["Date", "SeriesId", "GameNumber", "Away", "Home"])
    df = df.drop_duplicates(subset=["Date", "Away", "Home"], keep="last")
    return df


def fetch_postseason_results_espn(days_back: int = 14) -> pd.DataFrame:
    rows: list[dict] = []
    by_series: dict[str, list[dict]] = {}

    session = requests.Session()
    session.trust_env = False
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
        }
    )

    for game_date in build_recent_date_range(days_back):
        date_token = game_date.replace("-", "")
        try:
            resp = session.get(f"{ESPN_SCOREBOARD_URL}?dates={date_token}", timeout=20)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            print(f"Skipping ESPN {game_date}: {exc}")
            continue

        events = payload.get("events", []) or []
        if not events:
            continue

        for event in events:
            competitions = event.get("competitions", []) or []
            if not competitions:
                continue
            competition = competitions[0]
            status_type = (((event.get("status") or {}).get("type")) or {})
            if not status_type.get("completed", False):
                continue

            competitors = competition.get("competitors", []) or []
            away_team = next((item for item in competitors if item.get("homeAway") == "away"), None)
            home_team = next((item for item in competitors if item.get("homeAway") == "home"), None)
            if not away_team or not home_team:
                continue

            away = normalize_team_abbreviation(((away_team.get("team") or {}).get("abbreviation")) or "")
            home = normalize_team_abbreviation(((home_team.get("team") or {}).get("abbreviation")) or "")
            if not away or not home:
                continue

            series_id = SERIES_LOOKUP.get(frozenset({away, home}))
            if not series_id:
                continue

            try:
                away_score = int(float(away_team.get("score", 0) or 0))
                home_score = int(float(home_team.get("score", 0) or 0))
            except Exception:
                continue

            series_rows = by_series.setdefault(series_id, [])
            row = {
                "Date": game_date,
                "Away": away,
                "Home": home,
                "AwayScore": away_score,
                "HomeScore": home_score,
                "SeriesId": series_id,
                "Round": infer_round(series_id),
                "GameNumber": infer_game_number(series_rows),
            }
            series_rows.append(row)
            rows.append(row)

        time.sleep(0.25)

    if not rows:
        return pd.DataFrame(columns=["Date", "Away", "Home", "AwayScore", "HomeScore", "SeriesId", "Round", "GameNumber"])

    df = pd.DataFrame(rows).sort_values(["Date", "SeriesId", "GameNumber", "Away", "Home"])
    return df.drop_duplicates(subset=["Date", "Away", "Home"], keep="last")


def infer_results_from_playoff_logs() -> pd.DataFrame:
    if not PLAYOFF_GAMELOGS_PATH.exists():
        return pd.DataFrame(columns=["Date", "Away", "Home", "AwayScore", "HomeScore", "SeriesId", "Round", "GameNumber"])

    try:
        logs = pd.read_csv(PLAYOFF_GAMELOGS_PATH)
    except Exception as exc:
        print(f"Could not read playoff gamelogs: {exc}")
        return pd.DataFrame(columns=["Date", "Away", "Home", "AwayScore", "HomeScore", "SeriesId", "Round", "GameNumber"])

    required = {"Game_ID", "Date", "Matchup", "PTS"}
    if logs.empty or not required.issubset(set(logs.columns)):
        return pd.DataFrame(columns=["Date", "Away", "Home", "AwayScore", "HomeScore", "SeriesId", "Round", "GameNumber"])

    rows: list[dict] = []
    by_series: dict[str, list[dict]] = {}

    for game_id, game_logs in logs.groupby("Game_ID"):
        if len(game_logs) < 2:
            continue

        matchup_totals = (
            game_logs.groupby("Matchup", dropna=True)["PTS"]
            .sum()
            .sort_index()
        )
        if len(matchup_totals) != 2:
            continue

        date_text = str(game_logs.iloc[0].get("Date", "")).strip()
        try:
            game_date = pd.to_datetime(date_text, errors="coerce").strftime("%Y-%m-%d")
        except Exception:
            game_date = ""
        if not game_date or game_date == "NaT":
            continue

        away = None
        home = None
        away_score = None
        home_score = None
        for matchup_text, score in matchup_totals.items():
            matchup = str(matchup_text).strip()
            if " vs. " in matchup:
                team, opp = matchup.split(" vs. ", 1)
                home = team.strip().upper()
                away = opp.strip().upper()
                home_score = int(score)
            elif " @ " in matchup:
                team, opp = matchup.split(" @ ", 1)
                away = team.strip().upper()
                home = opp.strip().upper()
                away_score = int(score)
            else:
                break

        if not away or not home or away_score is None or home_score is None:
            continue

        series_id = SERIES_LOOKUP.get(frozenset({away, home}))
        if not series_id:
            continue

        series_rows = by_series.setdefault(series_id, [])
        row = {
            "Date": game_date,
            "Away": away,
            "Home": home,
            "AwayScore": int(away_score),
            "HomeScore": int(home_score),
            "SeriesId": series_id,
            "Round": infer_round(series_id),
            "GameNumber": infer_game_number(series_rows),
        }
        series_rows.append(row)
        rows.append(row)

    if not rows:
        return pd.DataFrame(columns=["Date", "Away", "Home", "AwayScore", "HomeScore", "SeriesId", "Round", "GameNumber"])

    df = pd.DataFrame(rows).sort_values(["Date", "SeriesId", "GameNumber", "Away", "Home"])
    return df.drop_duplicates(subset=["Date", "Away", "Home"], keep="last")


def load_existing_results() -> pd.DataFrame:
    if not OUTPUT_PATH.exists():
        return pd.DataFrame(columns=["Date", "Away", "Home", "AwayScore", "HomeScore", "SeriesId", "Round", "GameNumber"])
    try:
        df = pd.read_csv(OUTPUT_PATH)
    except Exception as exc:
        print(f"Could not read existing playoff results: {exc}")
        return pd.DataFrame(columns=["Date", "Away", "Home", "AwayScore", "HomeScore", "SeriesId", "Round", "GameNumber"])
    df["SourcePriority"] = 0
    return df


def merge_result_sources(*frames: pd.DataFrame) -> pd.DataFrame:
    valid_frames = [frame.copy() for frame in frames if frame is not None and not frame.empty]
    if not valid_frames:
        return pd.DataFrame(columns=["Date", "Away", "Home", "AwayScore", "HomeScore", "SeriesId", "Round", "GameNumber"])

    merged = pd.concat(valid_frames, ignore_index=True, sort=False)
    for col in ["Date", "Away", "Home", "SeriesId", "Round"]:
        if col not in merged.columns:
            merged[col] = ""
    for col in ["AwayScore", "HomeScore"]:
        if col not in merged.columns:
            merged[col] = 0
        merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0).astype(int)
    if "SourcePriority" not in merged.columns:
        merged["SourcePriority"] = 0
    merged["SourcePriority"] = pd.to_numeric(merged["SourcePriority"], errors="coerce").fillna(0).astype(int)

    merged["Date"] = pd.to_datetime(merged["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
    merged = merged.dropna(subset=["Date"])
    merged["score_total"] = merged["AwayScore"] + merged["HomeScore"]

    merged = (
        merged.sort_values(["Date", "SeriesId", "SourcePriority", "score_total"])
        .drop_duplicates(subset=["Date", "Away", "Home"], keep="last")
    )

    rebuilt_rows: list[dict] = []
    for series_id, series_df in merged.groupby("SeriesId", dropna=False):
        series_df = series_df.sort_values(["Date", "Away", "Home"]).reset_index(drop=True)
        for idx, (_, row) in enumerate(series_df.iterrows(), start=1):
            rebuilt_rows.append({
                "Date": row["Date"],
                "Away": row["Away"],
                "Home": row["Home"],
                "AwayScore": int(row["AwayScore"]),
                "HomeScore": int(row["HomeScore"]),
                "SeriesId": row["SeriesId"],
                "Round": row["Round"] or infer_round(str(row["SeriesId"])),
                "GameNumber": idx,
            })

    return pd.DataFrame(rebuilt_rows).sort_values(["Date", "SeriesId", "GameNumber", "Away", "Home"])


def main() -> int:
    print("=" * 60)
    print("BANKROLL KINGS - Refresh Playoff Results")
    print("=" * 60)
    fetched = fetch_postseason_results(days_back=14)
    espn_fetched = fetch_postseason_results_espn(days_back=14)
    inferred = infer_results_from_playoff_logs()
    existing = load_existing_results()
    fetched["SourcePriority"] = 2
    espn_fetched["SourcePriority"] = 3
    inferred["SourcePriority"] = 1
    df = merge_result_sources(existing, inferred, fetched, espn_fetched)
    df.to_csv(OUTPUT_PATH, index=False)
    print(f"Saved {len(df)} playoff/play-in results to {OUTPUT_PATH}")
    if not df.empty:
        print(df.tail(10).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
