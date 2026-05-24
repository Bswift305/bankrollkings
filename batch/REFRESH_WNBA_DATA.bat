@echo off
cd /d C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls
echo ============================================================
echo   BANKROLL KINGS - WNBA DATA REFRESH
echo   %date% %time%
echo ============================================================
echo.
echo [1/3] Refreshing WNBA game lines...
if "%ODDS_API_KEY%"=="" (
    echo ODDS_API_KEY not set - skipping WNBA game lines.
) else (
    py fetch_wnba_game_lines.py --days 5
)
echo.
echo [2/3] Refreshing WNBA player props...
if "%ODDS_API_KEY%"=="" (
    echo ODDS_API_KEY not set - skipping WNBA player props.
) else (
    py fetch_wnba_player_props.py --days 5
)
echo.
echo [3/6] Refreshing WNBA player logs...
py refresh_wnba_player_logs.py
echo.
echo [4/6] Archiving candidate review rows...
py archive_daily_candidates.py
echo.
echo [5/6] Refreshing WNBA featured results...
py refresh_wnba_featured_results.py
echo.
echo [6/7] Refreshing full-board prop results...
py refresh_all_prop_results.py
echo.
echo [7/7] Calibrating WNBA model feedback...
py calibrate_wnba_model.py
echo.
echo ============================================================
echo   COMPLETE! Window will close in 10 seconds...
echo ============================================================
timeout /t 10
