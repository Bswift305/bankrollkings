@echo off
cd /d C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls
echo ============================================================
echo   BANKROLL KINGS - MLB DATA REFRESH
echo   %date% %time%
echo ============================================================
echo.
echo [1/5] Refreshing MLB schedule...
py -X utf8 fetch_mlb_schedule.py --days 14
echo.
echo [2/5] Refreshing MLB game logs...
py -X utf8 fetch_mlb_gamelogs.py --initial-days 10
echo.
echo [3/5] Refreshing MLB game lines...
if "%ODDS_API_KEY%"=="" (
    echo ODDS_API_KEY not set - skipping MLB game lines.
) else (
    py fetch_mlb_game_lines.py --days 5
)
echo.
echo [4/5] Refreshing MLB player props...
if "%ODDS_API_KEY%"=="" (
    echo ODDS_API_KEY not set - skipping MLB player props.
) else (
    py fetch_mlb_player_props.py --days 5
)
echo.
echo [5/8] Running MLB readiness QC...
py qc_mlb_readiness.py
echo.
echo [6/8] Archiving candidate review rows...
py archive_daily_candidates.py
echo.
echo [7/8] Refreshing MLB featured results...
py refresh_mlb_featured_results.py
echo.
echo [8/9] Refreshing full-board prop results...
py refresh_all_prop_results.py
echo.
echo [9/9] Calibrating MLB model feedback...
py calibrate_mlb_model.py
echo.
echo ============================================================
echo   COMPLETE! Window will close in 10 seconds...
echo ============================================================
timeout /t 10
