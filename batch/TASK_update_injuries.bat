@echo off
REM For Task Scheduler - runs silently, logs output
cd /d C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls
if not exist logs mkdir logs
py refresh_all_sport_injuries.py >> logs\injuries_%date:~-4,4%%date:~-10,2%%date:~-7,2%.log 2>&1
