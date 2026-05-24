"""
Bankroll Kings - Fetch Odds & Schedule
======================================
Run directly with: py fetch_odds.py
"""

import os
from datetime import datetime, timedelta
from pathlib import Path

print("\n" + "=" * 50)
print("  BANKROLL KINGS - Fetch Today's Games & Odds")
print("=" * 50)


def _disable_dead_local_proxies():
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

BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
SCHEDULES_DIR = DATA_DIR / "schedules"
ODDS_DIR = DATA_DIR / "odds"

SCHEDULES_DIR.mkdir(parents=True, exist_ok=True)

try:
    import pandas as pd
except ImportError:
    print("Installing pandas...")
    os.system("pip install pandas --break-system-packages")
    import pandas as pd

try:
    from nba_api.stats.endpoints import scoreboardv2
    from nba_api.stats.static import teams
except ImportError:
    print("Installing nba_api...")
    os.system("pip install nba_api --break-system-packages")
    from nba_api.stats.endpoints import scoreboardv2
    from nba_api.stats.static import teams


def get_team_abbrev_map():
    """Create mapping of team ID to abbreviation."""
    team_list = teams.get_teams()
    return {t["id"]: t["abbreviation"] for t in team_list}


TEAM_MAP = get_team_abbrev_map()


def load_odds_schedule_fallback():
    """Use fresh odds-backed schedule rows when NBA Stats schedule is empty."""
    candidate_paths = [
        SCHEDULES_DIR / "NBA_Odds.csv",
        ODDS_DIR / "NBA_Odds.csv",
    ]
    for path in candidate_paths:
        if not path.exists():
            continue
        try:
            df = pd.read_csv(path)
        except Exception as exc:
            print(f"    ! Could not read odds fallback from {path.name}: {exc}")
            continue
        required = {"Date", "Away", "Home"}
        if df.empty or not required.issubset(df.columns):
            continue
        keep_columns = [col for col in ["Date", "Away", "Home", "Time"] if col in df.columns]
        if "Time" not in keep_columns:
            df["Time"] = "TBD"
            keep_columns.append("Time")
        fallback_df = df[keep_columns].copy()
        fallback_df = fallback_df.dropna(subset=["Date", "Away", "Home"])
        fallback_df["Date"] = pd.to_datetime(fallback_df["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
        fallback_df["Away"] = fallback_df["Away"].astype(str).str.strip()
        fallback_df["Home"] = fallback_df["Home"].astype(str).str.strip()
        fallback_df["Time"] = fallback_df["Time"].astype(str).str.strip().replace({"": "TBD"})
        fallback_df = fallback_df.drop_duplicates(subset=["Date", "Away", "Home"]).sort_values(
            ["Date", "Time", "Away", "Home"]
        )
        if not fallback_df.empty:
            print(f"    [OK] Using odds-backed schedule fallback from {path.name}")
            return fallback_df.reset_index(drop=True)
    return pd.DataFrame(columns=["Date", "Away", "Home", "Time"])


def fetch_nba_schedule():
    """Fetch schedule from NBA Stats API."""
    print("\n[1] Fetching schedule from NBA Stats API...")

    import time

    schedule_data = []

    for days_ahead in range(7):
        game_date = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

        try:
            time.sleep(0.7)
            scoreboard = scoreboardv2.ScoreboardV2(game_date=game_date)
            games_df = scoreboard.get_data_frames()[0]

            if not games_df.empty:
                print(f"    [OK] {game_date}: {len(games_df)} games")

                if days_ahead == 0:
                    print(f"    Columns: {list(games_df.columns)[:10]}...")

                for _, game in games_df.iterrows():
                    home_team_id = game.get("HOME_TEAM_ID", None)
                    away_team_id = game.get("VISITOR_TEAM_ID", None)

                    home = TEAM_MAP.get(home_team_id, "")
                    away = TEAM_MAP.get(away_team_id, "")

                    if not home:
                        home = game.get("HOME_TEAM_ABBREVIATION", "")
                    if not away:
                        away = game.get("VISITOR_TEAM_ABBREVIATION", "")

                    game_status = game.get("GAME_STATUS_TEXT", "TBD")

                    if home and away and str(home) != "nan" and str(away) != "nan":
                        schedule_data.append(
                            {
                                "Date": game_date,
                                "Away": str(away),
                                "Home": str(home),
                                "Time": str(game_status),
                            }
                        )
                    else:
                        print(
                            f"    ! Missing team data - Home ID: {home_team_id}, Away ID: {away_team_id}"
                        )
            else:
                if days_ahead == 0:
                    print(f"    ! No games found for {game_date}")

        except Exception as e:
            print(f"    ! Error for {game_date}: {e}")
            continue

    if schedule_data:
        df = pd.DataFrame(schedule_data)
    else:
        df = load_odds_schedule_fallback()
        if df.empty:
            print("    ! No games found at all")
            return False

    df = df.drop_duplicates(subset=["Date", "Away", "Home"]).sort_values(
        ["Date", "Time", "Away", "Home"]
    )
    df.to_csv(SCHEDULES_DIR / "NBA_Schedule.csv", index=False)
    print(f"\n    [OK] Saved {len(df)} total games")

    today = datetime.now().strftime("%Y-%m-%d")
    todays = df[df["Date"] == today]

    print("\n" + "=" * 50)
    print(f"  TODAY'S GAMES ({today})")
    print("=" * 50)

    if not todays.empty:
        for _, g in todays.iterrows():
            print(f"    {g['Away']} @ {g['Home']} - {g['Time']}")
    else:
        print("    No games today")

    return True


if __name__ == "__main__":
    fetch_nba_schedule()

    print("\n" + "=" * 50)
    print("  DONE! Run RUN.bat to start the server")
    print("=" * 50 + "\n")
