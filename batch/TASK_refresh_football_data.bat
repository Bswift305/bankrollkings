@echo off
REM For Task Scheduler - runs silently, logs output
cd /d C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls
if not exist logs mkdir logs
echo === FOOTBALL DATA REFRESH %date% %time% === >> logs\refresh_football.log
if "%ODDS_API_KEY%"=="" (
    echo ODDS_API_KEY not set - skipping NFL game lines. >> logs\refresh_football.log
) else (
    py fetch_nfl_game_lines.py --days 7 >> logs\refresh_football.log 2>&1
)
if "%ODDS_API_KEY%"=="" (
    echo ODDS_API_KEY not set - skipping NFL player props. >> logs\refresh_football.log
) else (
    py fetch_nfl_player_props.py --days 7 >> logs\refresh_football.log 2>&1
)
if "%ODDS_API_KEY%"=="" (
    echo ODDS_API_KEY not set - skipping CFB game lines. >> logs\refresh_football.log
) else (
    py fetch_ncaaf_game_lines.py --days 7 >> logs\refresh_football.log 2>&1
)
if "%ODDS_API_KEY%"=="" (
    echo ODDS_API_KEY not set - skipping CFB player props. >> logs\refresh_football.log
) else (
    py fetch_ncaaf_player_props.py --days 7 >> logs\refresh_football.log 2>&1
)
if "%CFBD_API_KEY%"=="" (
    echo CFBD_API_KEY not set - skipping CFB current roster. >> logs\refresh_football.log
) else (
    py fetch_cfbd_current_roster.py --year 2026 --fallback-year 2025 >> logs\refresh_football.log 2>&1
)
if "%CFBD_API_KEY%"=="" (
    echo CFBD_API_KEY not set - skipping CFB player stats. >> logs\refresh_football.log
) else (
    py fetch_cfbd_player_stats.py --year 2025 >> logs\refresh_football.log 2>&1
)
if "%CFBD_API_KEY%"=="" (
    echo CFBD_API_KEY not set - skipping CFB returning production. >> logs\refresh_football.log
) else (
    py fetch_cfbd_returning_production.py --year 2026 --fallback-year 2025 >> logs\refresh_football.log 2>&1
)
if "%CFBD_API_KEY%"=="" (
    echo CFBD_API_KEY not set - skipping CFB transfer portal. >> logs\refresh_football.log
) else (
    py fetch_cfbd_transfer_portal.py --year 2026 >> logs\refresh_football.log 2>&1
    py build_ncaaf_player_master.py --last-season 2025 >> logs\refresh_football.log 2>&1
)
py refresh_runtime_snapshots.py >> logs\refresh_football.log 2>&1
echo === COMPLETE === >> logs\refresh_football.log
