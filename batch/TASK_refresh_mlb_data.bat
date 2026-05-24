@echo off
REM For Task Scheduler - runs silently, logs output
cd /d C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls
if not exist logs mkdir logs
echo === MLB DATA REFRESH %date% %time% === >> logs\refresh_mlb.log
py refresh_mlb_daily.py >> logs\refresh_mlb.log 2>&1
echo === COMPLETE === >> logs\refresh_mlb.log
