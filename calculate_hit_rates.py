"""
NBA Floor Plays Hit Rate Calculator
Processes game logs to find 80%+ hit rate props

Run this AFTER you've downloaded game logs with download_2025_26_game_logs.py
"""

import pandas as pd
from datetime import datetime

# =============================================================================
# CONFIGURATION
# =============================================================================
INPUT_FILE = 'nba_game_logs_2025-26.csv'  # File from downloader script
OUTPUT_FILE = 'floor_plays_analysis.xlsx'
MIN_GAMES = 10  # Minimum games to consider reliable
MIN_HIT_RATE = 0.80  # 80% threshold for floor plays

# Prop lines to test for each stat
PROP_LINES = {
    'PTS': [9.5, 14.5, 19.5, 24.5, 29.5, 34.5],
    'REB': [2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5, 10.5],
    'AST': [1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5],
    'STL': [0.5, 1.5, 2.5],
    'BLK': [0.5, 1.5, 2.5],
    'FG3M': [0.5, 1.5, 2.5, 3.5, 4.5],
}

# =============================================================================
# FUNCTIONS
# =============================================================================

def calculate_hit_rate(games, stat, line):
    """Calculate hit rate for a specific stat and line"""
    hits = (games[stat] > line).sum()
    total = len(games)
    return hits / total if total > 0 else 0

def analyze_player(player_games):
    """Analyze all prop lines for a single player"""
    results = []
    player_name = player_games['PLAYER_NAME'].iloc[0]
    if 'GAME_DATE' in player_games.columns:
        player_games = player_games.copy()
        player_games['GAME_DATE'] = pd.to_datetime(player_games['GAME_DATE'], errors='coerce')
        player_games = player_games.sort_values('GAME_DATE', ascending=False, na_position='last')
    games_played = len(player_games)
    
    for stat, lines in PROP_LINES.items():
        if stat not in player_games.columns:
            continue
            
        season_avg = player_games[stat].mean()
        
        for line in lines:
            hit_rate = calculate_hit_rate(player_games, stat, line)
            hits = (player_games[stat] > line).sum()
            
            results.append({
                'Player': player_name,
                'Games': games_played,
                'Stat': stat,
                'Line': line,
                'Hits': hits,
                'Hit_Rate': hit_rate,
                'Season_Avg': round(season_avg, 1),
                'Last_5_Avg': round(player_games[stat].head(5).mean(), 1),
            })
    
    return results

def find_floor_plays(all_results_df):
    """Filter to only floor plays (80%+ hit rate)"""
    floor_plays = all_results_df[
        (all_results_df['Hit_Rate'] >= MIN_HIT_RATE) &
        (all_results_df['Games'] >= MIN_GAMES)
    ].copy()
    
    floor_plays = floor_plays.sort_values('Hit_Rate', ascending=False)
    return floor_plays

def main():
    print("=" * 60)
    print("FLOOR PLAYS HIT RATE CALCULATOR")
    print("=" * 60)
    print()
    
    # Load data
    print(f"Loading {INPUT_FILE}...")
    try:
        df = pd.read_csv(INPUT_FILE)
    except FileNotFoundError:
        print(f"ERROR: {INPUT_FILE} not found!")
        print("Run download_2025_26_game_logs.py first to download the data.")
        return
    
    print(f"Loaded {len(df)} game logs for {df['PLAYER_NAME'].nunique()} players")
    print()
    
    # Analyze each player
    print("Analyzing hit rates for all players...")
    all_results = []
    
    players = df['PLAYER_NAME'].unique()
    for i, player in enumerate(players):
        player_games = df[df['PLAYER_NAME'] == player].copy()
        results = analyze_player(player_games)
        all_results.extend(results)
        
        if (i + 1) % 100 == 0:
            print(f"  Processed {i+1}/{len(players)} players...")
    
    # Convert to DataFrame
    results_df = pd.DataFrame(all_results)
    results_df['Hit_Rate_Pct'] = (results_df['Hit_Rate'] * 100).round(1)
    
    # Find floor plays
    floor_plays = find_floor_plays(results_df)
    
    # Create summary by player
    player_summary = df.groupby('PLAYER_NAME').agg({
        'PTS': ['count', 'mean'],
        'REB': 'mean',
        'AST': 'mean',
        'STL': 'mean',
        'BLK': 'mean',
        'FG3M': 'mean'
    }).round(1)
    player_summary.columns = ['Games', 'PPG', 'RPG', 'APG', 'SPG', 'BPG', '3PM']
    player_summary = player_summary.reset_index()
    player_summary = player_summary.sort_values('PPG', ascending=False)
    
    # Save to Excel with multiple sheets
    print()
    print(f"Saving analysis to {OUTPUT_FILE}...")
    
    with pd.ExcelWriter(OUTPUT_FILE, engine='openpyxl') as writer:
        # Sheet 1: Floor Plays (80%+)
        floor_plays.to_excel(writer, sheet_name='Floor Plays (80%+)', index=False)
        
        # Sheet 2: All Hit Rates
        results_df.to_excel(writer, sheet_name='All Hit Rates', index=False)
        
        # Sheet 3: Player Summary
        player_summary.to_excel(writer, sheet_name='Player Summary', index=False)
    
    # Print summary
    print()
    print("=" * 60)
    print("ANALYSIS COMPLETE!")
    print("=" * 60)
    print(f"Total players analyzed: {len(players)}")
    print(f"Total prop combinations tested: {len(results_df)}")
    print(f"Floor plays found (80%+ hit rate): {len(floor_plays)}")
    print()
    print(f"Output saved to: {OUTPUT_FILE}")
    print()
    print("SHEETS IN OUTPUT FILE:")
    print("  1. Floor Plays (80%+) - Your betting targets")
    print("  2. All Hit Rates - Every prop line tested")
    print("  3. Player Summary - Season averages")
    print()
    
    # Show top floor plays
    if len(floor_plays) > 0:
        print("TOP 20 FLOOR PLAYS:")
        print("-" * 60)
        top_20 = floor_plays.head(20)
        for _, row in top_20.iterrows():
            print(f"  {row['Player']}: {row['Stat']} Over {row['Line']} = {row['Hit_Rate_Pct']}% ({row['Hits']}/{row['Games']})")

if __name__ == "__main__":
    main()
