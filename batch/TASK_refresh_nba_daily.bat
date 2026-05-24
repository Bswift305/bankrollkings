@echo off
REM For Task Scheduler - runs silently, logs output
cd /d C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls
if not exist logs mkdir logs
echo === NBA DAILY REFRESH %date% %time% === >> logs\refresh_nba_daily.log
py refresh_nba_daily.py >> logs\refresh_nba_daily.log 2>&1
echo === COMPLETE === >> logs\refresh_nba_daily.log
