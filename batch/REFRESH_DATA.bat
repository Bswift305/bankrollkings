@echo off
cd /d C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls
echo ============================================================
echo   BANKROLL KINGS - MORNING DATA REFRESH
echo   %date% %time%
echo ============================================================
echo.
echo This is now the FAST slate refresh only.
echo Tracking stats and playoff player logs were moved out of this flow.
echo.
echo [1/5] Refreshing NBA schedule...
py -X utf8 fetch_schedule.py
echo.
echo [2/5] Refreshing NBA player props...
if "%ODDS_API_KEY%"=="" (
    echo ODDS_API_KEY not set - skipping player props.
) else (
    py -X utf8 fetch_player_props.py --bookmakers draftkings,caesars,fanduel,betmgm --days 5
)
echo.
echo [3/5] Refreshing NBA game lines...
if "%ODDS_API_KEY%"=="" (
    echo ODDS_API_KEY not set - skipping game lines.
) else (
    py -X utf8 fetch_game_lines.py --bookmakers draftkings,caesars,fanduel,betmgm --days 5
)
echo.
echo [4/5] Refreshing playoff results...
py -X utf8 refresh_playoff_results.py
echo.
echo [5/6] Refreshing injuries...
py -X utf8 fetch_injuries.py
echo.
echo [6/6] Archiving daily candidate boards...
py -X utf8 archive_daily_candidates.py
echo.
echo ============================================================
echo   COMPLETE! Window will close in 10 seconds...
echo ============================================================
timeout /t 10
