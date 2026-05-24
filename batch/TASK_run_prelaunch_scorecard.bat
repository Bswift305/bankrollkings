@echo off
REM For Task Scheduler - runs silently, logs output
cd /d C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls
if not exist logs mkdir logs
echo === PRELAUNCH SCORECARD %date% %time% === >> logs\prelaunch_scorecard.log
py run_prelaunch_scorecard.py >> logs\prelaunch_scorecard.log 2>&1
echo === COMPLETE === >> logs\prelaunch_scorecard.log
