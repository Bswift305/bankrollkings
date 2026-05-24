@echo off
cd /d C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls
echo ============================================================
echo   BANKROLL KINGS - SCHEDULE UPDATE
echo   %date% %time%
echo ============================================================
echo.
echo Fetching today's NBA schedule...
echo.
py fetch_odds.py
echo.
echo Fetching player props...
if "%ODDS_API_KEY%"=="" (
    echo ODDS_API_KEY not set - skipping player props.
) else (
    py fetch_player_props.py --bookmakers draftkings --days 5
)
echo.
echo ============================================================
echo   COMPLETE! Window will close in 10 seconds...
echo ============================================================
timeout /t 10
