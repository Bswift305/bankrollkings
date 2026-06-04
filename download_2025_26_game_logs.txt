"""
NBA 2025-26 Season Game Log Downloader
Downloads game-by-game stats for ALL NBA players

This gives you the raw data needed to calculate hit rates for floor plays.
"""

import pandas as pd
import time
from datetime import datetime

# Install nba_api if not installed: pip install nba_api
from nba_api.stats.static import players
from nba_api.stats.endpoints import playergamelog

# =============================================================================
# CONFIGURATION
# =============================================================================
SEASON = '2025-26'  # Current season
OUTPUT_CSV = f'nba_game_logs_{SEASON}.csv'
OUTPUT_XLSX = f'nba_game_logs_{SEASON}.xlsx'
DELAY_BETWEEN_REQUESTS = 0.6  # Seconds between API calls (avoid rate limiting)

# =============================================================================
# MAIN SCRIPT
# =============================================================================

def get_all_active_players():
    """Get list of all active NBA players"""
    all_players = players.get_active_players()
    print(f"Found {len(all_players)} active players")
    return all_players

def download_player_game_log(player_id, player_name, season):
    """Download game log for a single player"""
    try:
        game_log = playergamelog.PlayerGameLog(
            player_id=player_id,
            season=season,
            season_type_all_star='Regular Season'
        )
        df = game_log.get_data_frames()[0]
        
        if len(df) > 0:
            df['PLAYER_NAME'] = player_name
            df['PLAYER_ID'] = player_id
            return df
        return None
    except Exception as e:
        print(f"  Error for {player_name}: {e}")
        return None

def main():
    print("=" * 60)
    print(f"NBA {SEASON} GAME LOG DOWNLOADER")
    print("=" * 60)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Get all active players
    all_players = get_all_active_players()
    
    # Download game logs
    all_game_logs = []
    players_with_data = 0
    
    for i, player in enumerate(all_players):
        player_name = player['full_name']
        player_id = player['id']
        
        print(f"[{i+1}/{len(all_players)}] Downloading: {player_name}...", end=" ")
        
        df = download_player_game_log(player_id, player_name, SEASON)
        
        if df is not None and len(df) > 0:
            all_game_logs.append(df)
            players_with_data += 1
            print(f"✓ {len(df)} games")
        else:
            print("No games found")
        
        # Rate limiting
        time.sleep(DELAY_BETWEEN_REQUESTS)
    
    # Combine all data
    if all_game_logs:
        print()
        print("=" * 60)
        print("COMBINING DATA...")
        
        final_df = pd.concat(all_game_logs, ignore_index=True)
        
        # Reorder columns to put player info first
        cols = ['PLAYER_NAME', 'PLAYER_ID'] + [c for c in final_df.columns if c not in ['PLAYER_NAME', 'PLAYER_ID']]
        final_df = final_df[cols]
        
        # Save to CSV
        final_df.to_csv(OUTPUT_CSV, index=False)
        print(f"✓ Saved: {OUTPUT_CSV}")
        
        # Save to Excel
        final_df.to_excel(OUTPUT_XLSX, index=False)
        print(f"✓ Saved: {OUTPUT_XLSX}")
        
        # Summary
        print()
        print("=" * 60)
        print("DOWNLOAD COMPLETE!")
        print("=" * 60)
        print(f"Players with game data: {players_with_data}")
        print(f"Total game logs: {len(final_df)}")
        print(f"Columns: {list(final_df.columns)}")
        print()
        print("KEY STATS COLUMNS:")
        print("  PTS  = Points")
        print("  REB  = Rebounds")
        print("  AST  = Assists")
        print("  STL  = Steals")
        print("  BLK  = Blocks")
        print("  FG3M = 3-Pointers Made")
        print()
        print(f"Files saved in current directory:")
        print(f"  1. {OUTPUT_CSV}")
        print(f"  2. {OUTPUT_XLSX}")
        
    else:
        print("No game data found!")

if __name__ == "__main__":
    main()
