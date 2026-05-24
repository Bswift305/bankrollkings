@echo off
cd /d C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls
echo ============================================================
echo   BANKROLL KINGS - FOOTBALL DATA REFRESH
echo   %date% %time%
echo ============================================================
echo.
echo [1/8] Refreshing NFL game lines...
if "%ODDS_API_KEY%"=="" (
    echo ODDS_API_KEY not set - skipping NFL game lines.
) else (
    py fetch_nfl_game_lines.py --days 7
)
echo.
echo [2/8] Refreshing NFL player props...
if "%ODDS_API_KEY%"=="" (
    echo ODDS_API_KEY not set - skipping NFL player props.
) else (
    py fetch_nfl_player_props.py --days 7
)
echo.
echo [3/8] Refreshing CFB game lines...
if "%ODDS_API_KEY%"=="" (
    echo ODDS_API_KEY not set - skipping CFB game lines.
) else (
    py fetch_ncaaf_game_lines.py --days 7
)
echo.
echo [4/8] Refreshing CFB player props...
if "%ODDS_API_KEY%"=="" (
    echo ODDS_API_KEY not set - skipping CFB player props.
) else (
    py fetch_ncaaf_player_props.py --days 7
)
echo.
echo [5/8] Refreshing CFB current roster...
if "%CFBD_API_KEY%"=="" (
    echo CFBD_API_KEY not set - skipping CFB current roster.
) else (
    py fetch_cfbd_current_roster.py --year 2026 --fallback-year 2025
)
echo.
echo [6/8] Refreshing CFB last-season player stats...
if "%CFBD_API_KEY%"=="" (
    echo CFBD_API_KEY not set - skipping CFB player stats.
) else (
    py fetch_cfbd_player_stats.py --year 2025
)
echo.
echo [7/8] Refreshing CFB returning production...
if "%CFBD_API_KEY%"=="" (
    echo CFBD_API_KEY not set - skipping CFB returning production.
) else (
    py fetch_cfbd_returning_production.py --year 2026 --fallback-year 2025
)
echo.
echo [8/8] Refreshing CFB transfer portal...
if "%CFBD_API_KEY%"=="" (
    echo CFBD_API_KEY not set - skipping CFB transfer portal.
) else (
    py fetch_cfbd_transfer_portal.py --year 2026
    py build_ncaaf_player_master.py --last-season 2025
)
echo.
echo ============================================================
echo   COMPLETE! Window will close in 10 seconds...
echo ============================================================
timeout /t 10
