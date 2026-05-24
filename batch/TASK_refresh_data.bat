@echo off
REM For Task Scheduler - runs silently, logs output
cd /d C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls
if not exist logs mkdir logs
echo === DATA REFRESH %date% %time% === >> logs\refresh.log
echo [1/5] Refreshing NBA schedule...
echo [1/5] Refreshing NBA schedule... >> logs\refresh.log
py -X utf8 fetch_schedule.py >> logs\refresh.log 2>&1
if "%ODDS_API_KEY%"=="" (
    echo [2/5] Skipping NBA player props - ODDS_API_KEY not set.
    echo ODDS_API_KEY not set - skipping player props. >> logs\refresh.log
) else (
    echo [2/5] Refreshing NBA player props...
    echo [2/5] Refreshing NBA player props... >> logs\refresh.log
    py -X utf8 fetch_player_props.py --bookmakers draftkings,caesars,fanduel,betmgm --days 5 >> logs\refresh.log 2>&1
    echo [3/5] Refreshing NBA game lines...
    echo [3/5] Refreshing NBA game lines... >> logs\refresh.log
    py -X utf8 fetch_game_lines.py --bookmakers draftkings,caesars,fanduel,betmgm --days 5 >> logs\refresh.log 2>&1
)
echo [4/5] Refreshing playoff results...
echo [4/5] Refreshing playoff results... >> logs\refresh.log
py -X utf8 refresh_playoff_results.py >> logs\refresh.log 2>&1
echo [5/6] Refreshing injuries...
echo [5/6] Refreshing injuries... >> logs\refresh.log
py -X utf8 fetch_injuries.py >> logs\refresh.log 2>&1
echo [6/6] Archiving daily candidate boards...
echo [6/6] Archiving daily candidate boards... >> logs\refresh.log
py -X utf8 archive_daily_candidates.py >> logs\refresh.log 2>&1
echo COMPLETE
echo === COMPLETE === >> logs\refresh.log
