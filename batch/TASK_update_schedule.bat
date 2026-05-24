@echo off
REM For Task Scheduler - runs silently, logs output
cd /d C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls
if not exist logs mkdir logs
py fetch_odds.py >> logs\schedule_%date:~-4,4%%date:~-10,2%%date:~-7,2%.log 2>&1
if not "%ODDS_API_KEY%"=="" py fetch_player_props.py --bookmakers draftkings --days 5 >> logs\schedule_%date:~-4,4%%date:~-10,2%%date:~-7,2%.log 2>&1
