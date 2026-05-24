from __future__ import annotations

import argparse
import os
from pathlib import Path
import time

import pandas as pd
from nba_api.stats.endpoints import playergamelog
from nba_api.stats.static import players, teams


BASE_DIR = Path(__file__).resolve().parent
GAMELOG_DIR = BASE_DIR / "data" / "gamelogs"
GAMELOG_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_PATH = GAMELOG_DIR / "NBA_Playoff_GameLogs.csv"
SEASON = "2025-26"
ROSTER_PATH = BASE_DIR / "data" / "tracking" / "NBA_CurrentRoster_FromDoc.csv"
SCHEDULE_PATH = BASE_DIR / "data" / "schedules" / "NBA_Schedule.csv"
REQUEST_TIMEOUT = 8
DELAY_BETWEEN_PLAYERS = 0.15

POSTSEASON_TEAMS = {
    'ATL', 'BOS', 'CLE', 'DET', 'NYK', 'ORL', 'PHI', 'TOR',
    'DEN', 'HOU', 'LAL', 'MIN', 'OKC', 'PHX', 'POR', 'SAS'
}
TEAM_NAME_TO_ABBR = {
    str(team.get('full_name', '')).strip().upper(): str(team.get('abbreviation', '')).strip().upper()
    for team in teams.get_teams()
}


def load_postseason_roster_names() -> set[str]:
    if not ROSTER_PATH.exists():
        return set()
    try:
        roster_df = pd.read_csv(ROSTER_PATH)
    except Exception as exc:
        print(f"Could not read roster file for playoff filter: {exc}")
        return set()
    if roster_df.empty or 'Player' not in roster_df.columns or 'CurrentTeam' not in roster_df.columns:
        return set()
    filtered = roster_df[roster_df['CurrentTeam'].astype(str).str.upper().isin(POSTSEASON_TEAMS)].copy()
    return {
        str(name).strip()
        for name in filtered['Player'].dropna().tolist()
        if str(name).strip()
    }


def load_active_slate_teams() -> set[str]:
    if not SCHEDULE_PATH.exists():
        return set()
    try:
        schedule_df = pd.read_csv(SCHEDULE_PATH)
    except Exception as exc:
        print(f"Could not read schedule file for slate filter: {exc}")
        return set()
    if schedule_df.empty or 'Date' not in schedule_df.columns:
        return set()

    schedule_df = schedule_df.copy()
    schedule_df['DateParsed'] = pd.to_datetime(schedule_df['Date'], errors='coerce')
    schedule_df = schedule_df.dropna(subset=['DateParsed'])
    if schedule_df.empty:
        return set()

    today = pd.Timestamp.now().normalize()
    window_start = today - pd.Timedelta(days=1)
    cutoff = today + pd.Timedelta(days=1)
    active = schedule_df[
        (schedule_df['DateParsed'] >= window_start) &
        (schedule_df['DateParsed'] <= cutoff)
    ].copy()
    if active.empty:
        active = schedule_df[schedule_df['DateParsed'] >= today].copy().head(4)

    teams = set()
    for col in ['Away', 'Home']:
        if col in active.columns:
            teams.update(
                TEAM_NAME_TO_ABBR.get(str(team).strip().upper(), str(team).strip().upper())
                for team in active[col].dropna().tolist()
                if str(team).strip()
            )
    return teams & POSTSEASON_TEAMS


def download_player_playoff_log(player_id: int, player_name: str, timeout: int = REQUEST_TIMEOUT) -> pd.DataFrame | None:
    try:
        game_log = playergamelog.PlayerGameLog(
            player_id=player_id,
            season=SEASON,
            season_type_all_star='Playoffs',
            timeout=timeout,
        )
        df = game_log.get_data_frames()[0]
    except Exception as exc:
        print(f"  Skipping {player_name}: {exc}")
        return None

    if df is None or df.empty:
        return None

    df = df.copy()
    df['PLAYER_NAME'] = player_name
    return df


def load_existing_logs() -> pd.DataFrame:
    if not OUTPUT_PATH.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(OUTPUT_PATH)
    except Exception as exc:
        print(f"Could not read existing playoff log file: {exc}")
        return pd.DataFrame()


def main() -> int:
    for proxy_key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        proxy_value = os.environ.get(proxy_key, "")
        if proxy_value.strip().lower() == "http://127.0.0.1:9":
            os.environ.pop(proxy_key, None)

    parser = argparse.ArgumentParser(description="Refresh NBA playoff player logs for active playoff teams.")
    parser.add_argument("--timeout", type=int, default=REQUEST_TIMEOUT, help="Per-player API timeout in seconds")
    parser.add_argument("--delay", type=float, default=DELAY_BETWEEN_PLAYERS, help="Delay between player requests in seconds")
    args = parser.parse_args()

    print("=" * 60)
    print("BANKROLL KINGS - Refresh Playoff Player Logs")
    print("=" * 60)
    print(f"Per-player timeout: {args.timeout}s")
    print(f"Delay between players: {args.delay}s")

    active_players = players.get_active_players()
    postseason_roster_names = load_postseason_roster_names()
    active_slate_teams = load_active_slate_teams()
    if postseason_roster_names:
        if active_slate_teams:
            try:
                roster_df = pd.read_csv(ROSTER_PATH)
                active_slate_names = {
                    str(name).strip()
                    for _, row in roster_df.iterrows()
                    if str(row.get('CurrentTeam', '')).strip().upper() in active_slate_teams
                    for name in [row.get('Player', '')]
                    if str(name).strip()
                }
            except Exception:
                active_slate_names = set()
            if active_slate_names:
                active_players = [
                    player for player in active_players
                    if str(player.get('full_name', '')).strip() in active_slate_names
                ]
                print(f"Filtered to {len(active_players)} active slate players across {sorted(active_slate_teams)}")
            else:
                active_players = [
                    player for player in active_players
                    if str(player.get('full_name', '')).strip() in postseason_roster_names
                ]
                print(f"Filtered to {len(active_players)} current playoff-roster players")
        else:
            active_players = [
                player for player in active_players
                if str(player.get('full_name', '')).strip() in postseason_roster_names
            ]
            print(f"Filtered to {len(active_players)} current playoff-roster players")
    else:
        print("Roster filter unavailable - checking all active players")
    rows = []
    saved_players = 0
    refreshed_players: set[str] = set()

    for idx, player in enumerate(active_players, start=1):
        player_name = player['full_name']
        player_id = player['id']
        print(f"[{idx}/{len(active_players)}] {player_name}")
        df = download_player_playoff_log(player_id, player_name, timeout=args.timeout)
        if df is None or df.empty:
            time.sleep(args.delay)
            continue

        if 'TEAM_ABBREVIATION' in df.columns:
            df = df[df['TEAM_ABBREVIATION'].isin(POSTSEASON_TEAMS)].copy()
        if df.empty:
            time.sleep(args.delay)
            continue

        rename_map = {
            'PLAYER_NAME': 'Player',
            'PLAYER_ID': 'PlayerID',
            'GAME_DATE': 'Date',
            'MATCHUP': 'Matchup',
            'WL': 'Result',
            'TEAM_ABBREVIATION': 'Team',
            'FG3M': '3PM'
        }
        df = df.rename(columns=rename_map)
        keep_cols = [
            'SEASON_ID', 'Player', 'PlayerID', 'Game_ID', 'Date', 'Matchup', 'Result',
            'MIN', 'FGM', 'FGA', 'FG_PCT', '3PM', 'FG3A', 'FG3_PCT', 'FTM', 'FTA',
            'FT_PCT', 'OREB', 'DREB', 'REB', 'AST', 'STL', 'BLK', 'TOV', 'PF', 'PTS',
            'PLUS_MINUS', 'VIDEO_AVAILABLE', 'Team'
        ]
        existing_cols = [col for col in keep_cols if col in df.columns]
        df = df[existing_cols].copy()

        if 'Matchup' in df.columns:
            def infer_opp(matchup: str) -> str:
                parts = str(matchup).split()
                return parts[-1] if parts else ''
            df['Opp'] = df['Matchup'].map(infer_opp)

        rows.append(df)
        saved_players += 1
        refreshed_players.add(player_name)
        time.sleep(args.delay)

    if rows:
        final_df = pd.concat(rows, ignore_index=True)
        existing_df = load_existing_logs()
        if not existing_df.empty:
            if "Player" in existing_df.columns and refreshed_players:
                existing_df = existing_df[~existing_df["Player"].astype(str).isin(refreshed_players)].copy()
            final_df = pd.concat([existing_df, final_df], ignore_index=True, sort=False)
        dedupe_cols = [col for col in ["Player", "Game_ID"] if col in final_df.columns]
        if dedupe_cols:
            final_df = final_df.drop_duplicates(subset=dedupe_cols, keep="last")
        final_df.to_csv(OUTPUT_PATH, index=False)
        print(f"Saved {len(final_df)} playoff player logs for {saved_players} players to {OUTPUT_PATH}")
    else:
        existing_df = load_existing_logs()
        if not existing_df.empty:
            existing_df.to_csv(OUTPUT_PATH, index=False)
            print("No fresh playoff player logs found. Preserved the existing playoff log file.")
        else:
            pd.DataFrame().to_csv(OUTPUT_PATH, index=False)
            print("No playoff player logs found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
