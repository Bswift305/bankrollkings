"""
Bankroll Kings - Data Refresh Script
=====================================
Downloads NBA game logs, tracking stats, and advanced metrics
"""

import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# Ensure unbuffered output
os.environ['PYTHONUNBUFFERED'] = '1'

def print_flush(msg):
    print(msg, flush=True)

def print_progress(current, total, extra=""):
    pct = int((current / total) * 100)
    bar_len = 30
    filled = int(bar_len * current / total)
    bar = '#' * filled + '-' * (bar_len - filled)
    print(f"\r    [{bar}] {current}/{total} ({pct}%) {extra[:30]:<30}", end='', flush=True)

print_flush("\n" + "="*60)
print_flush("  BANKROLL KINGS - Data Refresh")
print_flush("="*60)

# Setup paths
BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / 'data'
GAMELOGS_DIR = DATA_DIR / 'gamelogs'
SCHEDULES_DIR = DATA_DIR / 'schedules'
PROPS_DIR = DATA_DIR / 'props'
INJURIES_DIR = DATA_DIR / 'injuries'
TRACKING_DIR = DATA_DIR / 'tracking'

# Create directories
for d in [GAMELOGS_DIR, SCHEDULES_DIR, PROPS_DIR, INJURIES_DIR, TRACKING_DIR]:
    d.mkdir(parents=True, exist_ok=True)

print_flush(f"\n[{datetime.now().strftime('%H:%M:%S')}] Checking dependencies...")

try:
    import pandas as pd
    print_flush("  ✓ pandas")
except ImportError:
    print_flush("  Installing pandas...")
    os.system('pip install pandas --break-system-packages')
    import pandas as pd

try:
    from nba_api.stats.static import players, teams
    from nba_api.stats.endpoints import (
        playergamelog, 
        scoreboardv2,
        leaguedashptstats,
        leaguedashplayerstats,
        leaguedashptdefend
    )
    print_flush("  ✓ nba_api")
except ImportError:
    print_flush("  Installing nba_api...")
    os.system('pip install nba_api --break-system-packages')
    from nba_api.stats.static import players, teams
    from nba_api.stats.endpoints import (
        playergamelog, 
        scoreboardv2,
        leaguedashptstats,
        leaguedashplayerstats,
        leaguedashptdefend
    )

# Get current season
now = datetime.now()
if now.month >= 10:
    SEASON = f"{now.year}-{str(now.year + 1)[2:]}"
else:
    SEASON = f"{now.year - 1}-{str(now.year)[2:]}"

print_flush(f"\n[{datetime.now().strftime('%H:%M:%S')}] Season: {SEASON}")

# =============================================================================
# 1. DOWNLOAD TRACKING STATS (Speed, Distance, Touches, Drives)
# =============================================================================
print_flush(f"\n[{datetime.now().strftime('%H:%M:%S')}] Downloading tracking stats...")

try:
    time.sleep(1)
    tracking = leaguedashptstats.LeagueDashPtStats(
        season=SEASON,
        per_mode_simple='PerGame',
        player_or_team='Player'
    )
    tracking_df = tracking.get_data_frames()[0]
    
    # Save tracking stats
    tracking_path = TRACKING_DIR / 'NBA_Tracking.csv'
    tracking_df.to_csv(tracking_path, index=False)
    print_flush(f"  ✓ Tracking stats: {len(tracking_df)} players")
    print_flush(f"    Columns: TOUCHES, AVG_SPEED, DIST_MILES, DRIVES, CATCH_SHOOT_FGM, PULL_UP_FGM")
except Exception as e:
    print_flush(f"  ✗ Tracking stats failed: {e}")
    tracking_df = pd.DataFrame()

# =============================================================================
# 2. DOWNLOAD ADVANCED STATS (Usage, TS%, etc.)
# =============================================================================
print_flush(f"\n[{datetime.now().strftime('%H:%M:%S')}] Downloading advanced stats...")

try:
    time.sleep(1)
    advanced = leaguedashplayerstats.LeagueDashPlayerStats(
        season=SEASON,
        per_mode_detailed='PerGame',
        measure_type_detailed_defense='Advanced'
    )
    advanced_df = advanced.get_data_frames()[0]
    
    # Save advanced stats
    advanced_path = TRACKING_DIR / 'NBA_Advanced.csv'
    advanced_df.to_csv(advanced_path, index=False)
    print_flush(f"  ✓ Advanced stats: {len(advanced_df)} players")
    print_flush(f"    Columns: USG_PCT, TS_PCT, AST_PCT, OREB_PCT, DREB_PCT, NET_RATING")
except Exception as e:
    print_flush(f"  ✗ Advanced stats failed: {e}")
    advanced_df = pd.DataFrame()

# =============================================================================
# 3. DOWNLOAD DEFENSIVE TRACKING (Contested Shots, DFG%)
# =============================================================================
print_flush(f"\n[{datetime.now().strftime('%H:%M:%S')}] Downloading defensive tracking...")

try:
    time.sleep(1)
    defense = leaguedashptdefend.LeagueDashPtDefend(
        season=SEASON,
        per_mode_simple='PerGame',
        defense_category='Overall'
    )
    defense_df = defense.get_data_frames()[0]
    
    # Save defensive stats
    defense_path = TRACKING_DIR / 'NBA_Defense.csv'
    defense_df.to_csv(defense_path, index=False)
    print_flush(f"  ✓ Defensive tracking: {len(defense_df)} players")
    print_flush(f"    Columns: D_FGM, D_FGA, D_FG_PCT, NORMAL_FG_PCT, PCT_PLUSMINUS")
except Exception as e:
    print_flush(f"  ✗ Defensive tracking failed: {e}")
    defense_df = pd.DataFrame()

# =============================================================================
# 4. DOWNLOAD GAME LOGS
# =============================================================================
print_flush(f"\n[{datetime.now().strftime('%H:%M:%S')}] Getting active players...")
all_players = players.get_active_players()
print_flush(f"  Found {len(all_players)} active players")

player_list = all_players[:500]

print_flush(f"\n[{datetime.now().strftime('%H:%M:%S')}] Downloading game logs...")
print_flush(f"  This may take 10-15 minutes (API rate limits)")
print_flush("")

all_logs = []
success_count = 0
error_count = 0

for i, player in enumerate(player_list):
    player_id = player['id']
    player_name = player['full_name']
    
    print_progress(i + 1, len(player_list), player_name)
    
    try:
        time.sleep(0.6)
        
        gamelog = playergamelog.PlayerGameLog(
            player_id=player_id,
            season=SEASON,
            season_type_all_star='Regular Season'
        )
        
        df = gamelog.get_data_frames()[0]
        
        if not df.empty:
            df['Player'] = player_name
            df['PlayerID'] = player_id
            all_logs.append(df)
            success_count += 1
            
    except Exception as e:
        error_count += 1
        continue

print_flush("")
print_flush(f"\n[{datetime.now().strftime('%H:%M:%S')}] Download complete!")
print_flush(f"  ✓ {success_count} players with data")
print_flush(f"  ✗ {error_count} errors/no data")

if all_logs:
    print_flush(f"\n[{datetime.now().strftime('%H:%M:%S')}] Processing game logs...")
    
    combined = pd.concat(all_logs, ignore_index=True)
    
    # Rename columns
    column_map = {
        'GAME_DATE': 'Date',
        'MATCHUP': 'Matchup',
        'WL': 'Result',
        'MIN': 'MIN',
        'PTS': 'PTS',
        'REB': 'REB',
        'AST': 'AST',
        'STL': 'STL',
        'BLK': 'BLK',
        'TOV': 'TOV',
        'FGM': 'FGM',
        'FGA': 'FGA',
        'FG3M': '3PM',
        'FG3A': '3PA',
        'FTM': 'FTM',
        'FTA': 'FTA',
        'PLUS_MINUS': 'PLUS_MINUS'
    }
    
    for old, new in column_map.items():
        if old in combined.columns:
            combined.rename(columns={old: new}, inplace=True)
    
    # Extract team and opponent
    if 'Matchup' in combined.columns:
        combined['Team'] = combined['Matchup'].apply(lambda x: x.split(' ')[0] if pd.notna(x) else '')
        combined['Opp'] = combined['Matchup'].apply(lambda x: x.split(' ')[-1] if pd.notna(x) else '')
    
    # Merge tracking stats if available
    if not tracking_df.empty:
        tracking_cols = ['PLAYER_NAME', 'TOUCHES', 'AVG_SPEED', 'DIST_MILES', 'DRIVES', 
                        'CATCH_SHOOT_FGM', 'CATCH_SHOOT_FGA', 'PULL_UP_FGM', 'PULL_UP_FGA']
        tracking_subset = tracking_df[[c for c in tracking_cols if c in tracking_df.columns]].copy()
        tracking_subset.rename(columns={'PLAYER_NAME': 'Player'}, inplace=True)
        
        # Add tracking averages to a separate file (per-player, not per-game)
        player_tracking = tracking_subset.copy()
        player_tracking.to_csv(TRACKING_DIR / 'NBA_PlayerTracking.csv', index=False)
        print_flush(f"  ✓ Player tracking saved")
    
    # Merge advanced stats if available
    if not advanced_df.empty:
        adv_cols = ['PLAYER_NAME', 'USG_PCT', 'TS_PCT', 'AST_PCT', 'AST_TO', 
                   'OREB_PCT', 'DREB_PCT', 'NET_RATING', 'OFF_RATING', 'DEF_RATING']
        adv_subset = advanced_df[[c for c in adv_cols if c in advanced_df.columns]].copy()
        adv_subset.rename(columns={'PLAYER_NAME': 'Player'}, inplace=True)
        adv_subset.to_csv(TRACKING_DIR / 'NBA_PlayerAdvanced.csv', index=False)
        print_flush(f"  ✓ Player advanced stats saved")
    
    # Save main game logs
    output_path = GAMELOGS_DIR / 'NBA_GameLogs.csv'
    combined.to_csv(output_path, index=False)
    
    print_flush(f"\n  ✓ Saved {len(combined)} game logs")
    print_flush(f"  ✓ {combined['Player'].nunique()} unique players")

# =============================================================================
# 5. GET SCHEDULE
# =============================================================================
print_flush(f"\n[{datetime.now().strftime('%H:%M:%S')}] Getting schedule...")

try:
    schedule_data = []
    
    for days_ahead in range(7):
        game_date = (datetime.now() + timedelta(days=days_ahead)).strftime('%Y-%m-%d')
        
        try:
            time.sleep(0.6)
            scoreboard = scoreboardv2.ScoreboardV2(game_date=game_date)
            games = scoreboard.get_data_frames()[0]
            
            if not games.empty:
                for _, game in games.iterrows():
                    schedule_data.append({
                        'Date': game_date,
                        'Away': game.get('VISITOR_TEAM_ABBREVIATION', ''),
                        'Home': game.get('HOME_TEAM_ABBREVIATION', ''),
                        'Time': game.get('GAME_STATUS_TEXT', 'TBD')
                    })
        except:
            continue
    
    if schedule_data:
        schedule_df = pd.DataFrame(schedule_data)
        schedule_path = SCHEDULES_DIR / 'NBA_Schedule.csv'
        schedule_df.to_csv(schedule_path, index=False)
        print_flush(f"  ✓ Saved {len(schedule_df)} scheduled games")
    else:
        print_flush("  ! No scheduled games found")
        
except Exception as e:
    print_flush(f"  ✗ Error getting schedule: {e}")

# Create empty props file if doesn't exist
props_path = PROPS_DIR / 'NBA_Props.csv'
if not props_path.exists():
    pd.DataFrame(columns=['Player', 'Stat', 'Line', 'Team']).to_csv(props_path, index=False)

print_flush("\n" + "="*60)
print_flush("  DATA REFRESH COMPLETE!")
print_flush("="*60)
print_flush(f"\n  Files saved to: {DATA_DIR}")
print_flush(f"\n  Data includes:")
print_flush(f"    • Game logs (PTS, REB, AST, STL, BLK, etc.)")
print_flush(f"    • Tracking stats (Touches, Speed, Drives)")
print_flush(f"    • Advanced stats (USG%, TS%, Ratings)")
print_flush(f"    • Defensive tracking (Contested shots, DFG%)")
print_flush(f"\n  Run RUN.bat to start the server")
print_flush("")

sys.exit(0)
