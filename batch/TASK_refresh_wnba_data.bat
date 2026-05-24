@echo off
REM For Task Scheduler - runs silently, logs output
cd /d C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls
if not exist logs mkdir logs
echo === WNBA DATA REFRESH %date% %time% === >> logs\refresh_wnba.log
py fetch_wnba_game_lines.py --days 5 >> logs\refresh_wnba.log 2>&1
py fetch_wnba_player_props.py --days 5 >> logs\refresh_wnba.log 2>&1
py refresh_wnba_player_logs.py >> logs\refresh_wnba.log 2>&1
py archive_daily_candidates.py >> logs\refresh_wnba.log 2>&1
py refresh_wnba_featured_results.py >> logs\refresh_wnba.log 2>&1
py refresh_all_prop_results.py >> logs\refresh_wnba.log 2>&1
py calibrate_wnba_model.py >> logs\refresh_wnba.log 2>&1
py refresh_runtime_snapshots.py >> logs\refresh_wnba.log 2>&1
echo === COMPLETE === >> logs\refresh_wnba.log
