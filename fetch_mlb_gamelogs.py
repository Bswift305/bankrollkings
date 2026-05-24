from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_PATH = BASE_DIR / "data" / "gamelogs" / "MLB_GameLogs.csv"
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
MLB_TEAM_ABBR = {
    "Arizona Diamondbacks": "AZ",
    "Atlanta Braves": "ATL",
    "Athletics": "ATH",
    "Baltimore Orioles": "BAL",
    "Boston Red Sox": "BOS",
    "Chicago Cubs": "CHC",
    "Chicago White Sox": "CWS",
    "Cincinnati Reds": "CIN",
    "Cleveland Guardians": "CLE",
    "Colorado Rockies": "COL",
    "Detroit Tigers": "DET",
    "Houston Astros": "HOU",
    "Kansas City Royals": "KC",
    "Los Angeles Angels": "LAA",
    "Los Angeles Dodgers": "LAD",
    "Miami Marlins": "MIA",
    "Milwaukee Brewers": "MIL",
    "Minnesota Twins": "MIN",
    "New York Mets": "NYM",
    "New York Yankees": "NYY",
    "Philadelphia Phillies": "PHI",
    "Pittsburgh Pirates": "PIT",
    "San Diego Padres": "SD",
    "San Francisco Giants": "SF",
    "Seattle Mariners": "SEA",
    "St. Louis Cardinals": "STL",
    "Tampa Bay Rays": "TB",
    "Texas Rangers": "TEX",
    "Toronto Blue Jays": "TOR",
    "Washington Nationals": "WSH",
}


def get_json(url: str) -> dict:
    with urlopen(url, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def build_url(path: str, **params) -> str:
    clean_params = {k: v for k, v in params.items() if v not in [None, ""]}
    return f"https://statsapi.mlb.com{path}?{urlencode(clean_params)}"


def season_default_start(today: datetime | None = None) -> str:
    now = today or datetime.now()
    return f"{now.year}-03-01"


def fetch_schedule(start_date: str, end_date: str) -> list[dict]:
    url = build_url("/api/v1/schedule", sportId=1, startDate=start_date, endDate=end_date)
    payload = get_json(url)
    games: list[dict] = []
    for date_block in payload.get("dates", []):
        for game in date_block.get("games", []):
            if str(game.get("status", {}).get("abstractGameState") or "").strip().lower() != "final":
                continue
            away = game.get("teams", {}).get("away", {})
            home = game.get("teams", {}).get("home", {})
            games.append({
                "gamePk": game.get("gamePk"),
                "date": str(date_block.get("date") or ""),
                "away_abbr": str(away.get("team", {}).get("abbreviation") or "").strip(),
                "home_abbr": str(home.get("team", {}).get("abbreviation") or "").strip(),
                "away_name": str(away.get("team", {}).get("name") or "").strip(),
                "home_name": str(home.get("team", {}).get("name") or "").strip(),
                "away_runs": int(away.get("score", 0) or 0),
                "home_runs": int(home.get("score", 0) or 0),
            })
    return games


def parse_float(value) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def parse_outs_from_ip(ip_value) -> int:
    text = str(ip_value or "").strip()
    if not text:
        return 0
    if "." not in text:
        try:
            return int(float(text) * 3)
        except Exception:
            return 0
    whole, frac = text.split(".", 1)
    try:
        innings = int(whole)
        partial = int(frac[:1]) if frac else 0
    except Exception:
        return 0
    return innings * 3 + partial


def build_player_rows(game_meta: dict, boxscore: dict) -> list[dict]:
    rows: list[dict] = []
    teams = boxscore.get("teams", {})
    away_abbr = str(game_meta.get("away_abbr") or "").strip() or str(((teams.get("away") or {}).get("team") or {}).get("abbreviation") or "").strip()
    home_abbr = str(game_meta.get("home_abbr") or "").strip() or str(((teams.get("home") or {}).get("team") or {}).get("abbreviation") or "").strip()
    if not away_abbr:
        away_abbr = MLB_TEAM_ABBR.get(str(game_meta.get("away_name") or "").strip(), "")
    if not home_abbr:
        home_abbr = MLB_TEAM_ABBR.get(str(game_meta.get("home_name") or "").strip(), "")
    away_runs = game_meta["away_runs"]
    home_runs = game_meta["home_runs"]

    for side_key in ("away", "home"):
        team_payload = teams.get(side_key, {}) or {}
        team_info = team_payload.get("team", {}) or {}
        team_abbr = str(team_info.get("abbreviation") or "").strip()
        if not team_abbr:
            team_abbr = MLB_TEAM_ABBR.get(str(team_info.get("name") or "").strip(), "")
        opp_abbr = home_abbr if team_abbr == away_abbr else away_abbr
        matchup = f"{team_abbr} @ {opp_abbr}" if team_abbr == away_abbr else f"{team_abbr} vs. {opp_abbr}"
        team_runs = away_runs if team_abbr == away_abbr else home_runs
        opp_runs = home_runs if team_abbr == away_abbr else away_runs
        result = "W" if team_runs > opp_runs else "L" if team_runs < opp_runs else "T"

        for player in (team_payload.get("players") or {}).values():
            person = player.get("person", {}) or {}
            stats = player.get("stats", {}) or {}
            batting = stats.get("batting", {}) or {}
            pitching = stats.get("pitching", {}) or {}
            fielding = stats.get("fielding", {}) or {}
            position = str((player.get("position") or {}).get("abbreviation") or "").strip().upper()
            player_name = str(person.get("fullName") or "").strip()
            player_id = player.get("person", {}).get("id")
            if not player_name:
                continue

            row = {
                "Date": game_meta["date"],
                "GameID": game_meta["gamePk"],
                "Player": player_name,
                "PlayerID": player_id,
                "Team": team_abbr,
                "Opp": opp_abbr,
                "Matchup": matchup,
                "Result": result,
                "Position": position,
                "AB": int(batting.get("atBats", 0) or 0),
                "H": int(batting.get("hits", 0) or 0),
                "2B": int(batting.get("doubles", 0) or 0),
                "3B": int(batting.get("triples", 0) or 0),
                "R": int(batting.get("runs", 0) or 0),
                "RBI": int(batting.get("rbi", 0) or 0),
                "HR": int(batting.get("homeRuns", 0) or 0),
                "TB": int(batting.get("totalBases", 0) or 0),
                "BB": int(batting.get("baseOnBalls", 0) or 0),
                "SO": int(batting.get("strikeOuts", 0) or 0),
                "SB": int(batting.get("stolenBases", 0) or 0),
                "IP": str(pitching.get("inningsPitched") or "").strip(),
                "P_H": int(pitching.get("hits", 0) or 0),
                "P_R": int(pitching.get("runs", 0) or 0),
                "P_ER": int(pitching.get("earnedRuns", 0) or 0),
                "P_BB": int(pitching.get("baseOnBalls", 0) or 0),
                "P_SO": int(pitching.get("strikeOuts", 0) or 0),
                "P_OUTS": parse_outs_from_ip(pitching.get("inningsPitched")),
                "P_PITCHES": int(pitching.get("numberOfPitches", 0) or 0),
                "P_ERA": parse_float(pitching.get("era")),
                "PUTOUTS": int(fielding.get("putOuts", 0) or 0),
            }
            row["1B"] = max(int(row["H"]) - int(row["2B"]) - int(row["3B"]) - int(row["HR"]), 0)
            stat_sum = sum(
                int(row.get(col, 0) or 0)
                for col in ["AB", "H", "1B", "2B", "3B", "R", "RBI", "HR", "TB", "BB", "SO", "SB", "P_H", "P_R", "P_ER", "P_BB", "P_SO", "P_OUTS", "P_PITCHES", "PUTOUTS"]
            )
            if stat_sum <= 0 and not row.get("IP"):
                continue
            rows.append(row)
    return rows


def fetch_boxscore_rows(game_meta: dict) -> list[dict]:
    url = build_url(f"/api/v1/game/{game_meta['gamePk']}/boxscore")
    payload = get_json(url)
    return build_player_rows(game_meta, payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch MLB player game logs from MLB Stats API")
    parser.add_argument("--start-date", default="", help="YYYY-MM-DD; defaults to current season start.")
    parser.add_argument("--end-date", default="", help="YYYY-MM-DD; defaults to today.")
    parser.add_argument("--backfill-days", type=int, default=2, help="When existing logs are present, step back this many days before refreshing.")
    parser.add_argument("--initial-days", type=int, default=10, help="When no log file exists yet, only fetch this many recent days by default.")
    args = parser.parse_args()

    existing = pd.DataFrame()
    if OUTPUT_PATH.exists():
        try:
            existing = pd.read_csv(OUTPUT_PATH)
        except Exception:
            existing = pd.DataFrame()

    end_date = args.end_date or datetime.now().date().isoformat()
    if args.start_date:
        start_date = args.start_date
    elif not existing.empty and "Date" in existing.columns:
        last_date = pd.to_datetime(existing["Date"], errors="coerce").max()
        if pd.notna(last_date):
            start_date = (last_date.date() - timedelta(days=max(args.backfill_days, 0))).isoformat()
        else:
            start_date = (datetime.now().date() - timedelta(days=max(args.initial_days, 1))).isoformat()
    else:
        start_date = (datetime.now().date() - timedelta(days=max(args.initial_days, 1))).isoformat()

    print("=" * 60)
    print("BANKROLL KINGS - Refresh MLB Game Logs")
    print("=" * 60)
    print(f"Window: {start_date} -> {end_date}")

    games = fetch_schedule(start_date, end_date)
    rows: list[dict] = []
    for idx, game_meta in enumerate(games, start=1):
        print(f"[{idx}/{len(games)}] Game {game_meta['gamePk']} {game_meta['away_abbr']} @ {game_meta['home_abbr']}")
        try:
            rows.extend(fetch_boxscore_rows(game_meta))
        except Exception as exc:
            print(f"  WARN: failed to fetch game {game_meta['gamePk']}: {exc}")

    fresh = pd.DataFrame(rows)
    if not existing.empty:
        combined = pd.concat([existing, fresh], ignore_index=True, sort=False)
    else:
        combined = fresh

    if not combined.empty:
        dedupe_cols = [col for col in ["Date", "GameID", "PlayerID", "Team"] if col in combined.columns]
        if dedupe_cols:
            combined = combined.drop_duplicates(subset=dedupe_cols, keep="last")
        sort_cols = [col for col in ["Date", "GameID", "Team", "Player"] if col in combined.columns]
        if sort_cols:
            combined = combined.sort_values(sort_cols).reset_index(drop=True)

    combined.to_csv(OUTPUT_PATH, index=False)
    print(f"Saved {len(combined)} MLB game-log rows to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
