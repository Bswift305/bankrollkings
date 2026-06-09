@echo off
REM Daily Operator: Edge Engine analysis + 99/prelaunch scorecards + run-status
REM (the "Daily Engine Health" dashboard). Runs AFTER the morning sport-data
REM refreshes; --skip-refresh avoids re-fetching data the sport tasks already
REM pulled (no duplicate API spend).
cd /d C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls
if not exist logs mkdir logs
echo === DAILY OPERATOR %date% %time% === >> logs\daily_operator_task.log
py run_daily.py --skip-refresh --continue-on-error >> logs\daily_operator_task.log 2>&1
echo === COMPLETE === >> logs\daily_operator_task.log
