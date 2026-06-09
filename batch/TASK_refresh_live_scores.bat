@echo off
REM Task Scheduler - Live Scores poll (~60s). The script self-gates to game
REM windows, so off-hours runs are a cheap no-op that spend no API credits.
REM Log is overwritten each run (not appended) to stay small at this cadence.
cd /d C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls
if not exist logs mkdir logs
py refresh_live_scores.py > logs\refresh_live_scores.log 2>&1
