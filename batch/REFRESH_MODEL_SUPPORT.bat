@echo off
cd /d C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls
echo ============================================================
echo   BANKROLL KINGS - MODEL SUPPORT REFRESH
echo   %date% %time%
echo ============================================================
echo.
echo This is the slower maintenance refresh for deeper model context.
echo It is separate from the fast morning slate refresh on purpose.
echo.
echo [1/2] Refreshing tracking stats...
py -X utf8 refresh_tracking_stats.py
echo.
echo [2/2] Refreshing playoff player logs...
py -X utf8 refresh_playoff_player_logs.py --timeout 8 --delay 0.15
echo.
echo ============================================================
echo   COMPLETE! Window will close in 10 seconds...
echo ============================================================
timeout /t 10
