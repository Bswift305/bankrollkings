$ErrorActionPreference = "Stop"

$root = "C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls"
$batch = Join-Path $root "batch"

function New-BKTask {
    param(
        [string]$Name,
        [string]$Time,
        [string]$FileName
    )

    $scriptPath = Join-Path $batch $FileName
    if (!(Test-Path $scriptPath)) {
        throw "Missing task script: $scriptPath"
    }

    schtasks /Create /F /SC DAILY /TN $Name /TR $scriptPath /ST $Time | Out-Null
    Write-Host "Created task $Name at $Time -> $FileName"
}

Write-Host "Installing Bankroll Kings scheduled tasks..."

# Core morning refreshes
New-BKTask -Name "Bankroll Kings - NBA Daily Refresh" -Time "06:00" -FileName "TASK_refresh_nba_daily.bat"
New-BKTask -Name "Bankroll Kings - WNBA Refresh" -Time "07:00" -FileName "TASK_refresh_wnba_data.bat"
New-BKTask -Name "Bankroll Kings - MLB Refresh" -Time "08:00" -FileName "TASK_refresh_mlb_data.bat"
New-BKTask -Name "Bankroll Kings - Football Refresh" -Time "05:30" -FileName "TASK_refresh_football_data.bat"

# Intra-day support refreshes
New-BKTask -Name "Bankroll Kings - All Sport Injuries AM" -Time "10:30" -FileName "TASK_refresh_all_sport_injuries.bat"
New-BKTask -Name "Bankroll Kings - All Sport Injuries PM" -Time "15:30" -FileName "TASK_refresh_all_sport_injuries.bat"
New-BKTask -Name "Bankroll Kings - All Sport Injuries Evening" -Time "18:30" -FileName "TASK_refresh_all_sport_injuries.bat"

# Governance / reporting
New-BKTask -Name "Bankroll Kings - Prelaunch Scorecard" -Time "06:45" -FileName "TASK_run_prelaunch_scorecard.bat"

Write-Host ""
Write-Host "Scheduled tasks installed."
Write-Host "Use Task Scheduler or 'schtasks /Query /TN \"Bankroll Kings - NBA Daily Refresh\"' to verify."
