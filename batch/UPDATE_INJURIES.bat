@echo off
cd /d C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls
echo ============================================================
echo   BANKROLL KINGS - INJURY UPDATE
echo   %date% %time%
echo ============================================================
echo.
py refresh_all_sport_injuries.py
echo.
echo ============================================================
echo   COMPLETE! Window will close in 10 seconds...
echo ============================================================
timeout /t 10
