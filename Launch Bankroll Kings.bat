@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_bankroll_kings.ps1" -Port 5000
if errorlevel 1 pause
