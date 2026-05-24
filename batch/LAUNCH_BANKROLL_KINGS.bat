@echo off
cd /d C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls
echo ============================================================
echo   BANKROLL KINGS - STARTING SERVER
echo ============================================================
echo.
echo   Opening browser in 3 seconds...
timeout /t 3 >nul
start http://localhost:5000
echo.
echo   Server running - DO NOT CLOSE THIS WINDOW
echo   Press Ctrl+C to stop the server
echo.
py app.py
