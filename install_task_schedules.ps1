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

    # Use the structured ScheduledTasks cmdlets rather than `schtasks /TR`.
    # The project root contains a space ("Kings of Bankrolls"); passing the
    # path on a schtasks command line splits it at the first space, so the
    # action ends up executing "...\Kings" and the task dies with 0x80070002
    # (file not found). Building an action object keeps Execute as one field.
    $action  = New-ScheduledTaskAction -Execute $scriptPath -WorkingDirectory $root
    $trigger = New-ScheduledTaskTrigger -Daily -At $Time
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Force | Out-Null
    Write-Host "Created task $Name at $Time -> $FileName"
}

function New-BKMinuteTask {
    param(
        [string]$Name,
        [int]$EveryMinutes,
        [string]$FileName
    )

    $scriptPath = Join-Path $batch $FileName
    if (!(Test-Path $scriptPath)) {
        throw "Missing task script: $scriptPath"
    }

    # High-frequency poller (e.g. live in-game scores). schtasks /SC MINUTE
    # creates the repeating user task without needing elevation; we then repair
    # the action via the structured cmdlet so the spaced project path stays in a
    # single Execute field (a bare /TR would split it and fail with 0x80070002).
    schtasks /Create /F /SC MINUTE /MO $EveryMinutes /TN $Name /TR $scriptPath | Out-Null

    if ($FileName -like '*.vbs') {
        # Run the .vbs through wscript (a windowless host) so the cmd console
        # does NOT flash every minute when this high-frequency task fires.
        $action = New-ScheduledTaskAction -Execute "C:\Windows\System32\wscript.exe" `
            -Argument ("//B //Nologo `"$scriptPath`"") -WorkingDirectory $root
    } else {
        $action = New-ScheduledTaskAction -Execute $scriptPath -WorkingDirectory $root
    }
    Set-ScheduledTask -TaskName $Name -Action $action | Out-Null
    Write-Host "Created task $Name every $EveryMinutes min -> $FileName"
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

# Live in-game scores feed (polls every minute; the script self-gates to game
# windows, so off-hours runs are a cheap no-op that spend no API credits).
New-BKMinuteTask -Name "Bankroll Kings - Live Scores" -EveryMinutes 1 -FileName "run_live_scores_hidden.vbs"

Write-Host ""
Write-Host "Scheduled tasks installed."
Write-Host "Use Task Scheduler or 'schtasks /Query /TN \"Bankroll Kings - NBA Daily Refresh\"' to verify."
