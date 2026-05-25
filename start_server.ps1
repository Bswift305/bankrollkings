param(
    [int]$Port = 5000
)

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = 'C:\Users\Decatur\AppData\Local\Python\pythoncore-3.14-64\python.exe'
$RunDir = Join-Path $Root '.runtime'
$Runner = Join-Path $RunDir "run_bankroll_flask_$Port.py"
$PidFile = Join-Path $RunDir "server_$Port.pid"
$OutFile = Join-Path $RunDir "server_$Port.out.txt"
$ErrFile = Join-Path $RunDir "server_$Port.err.txt"

New-Item -ItemType Directory -Force -Path $RunDir | Out-Null

$existing = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match 'python' -and
    $_.CommandLine -match [regex]::Escape($Runner)
}

if ($existing) {
    Write-Host "Bankroll Kings is already running on port $Port. PID: $($existing.ProcessId -join ', ')"
    Write-Host "Open: http://localhost:$Port/"
    exit 0
}

$escapedRoot = $Root.Replace('\', '\\')
$runnerCode = @"
import sys
sys.path.insert(0, r"$escapedRoot")
from app import app
app.run(debug=False, use_reloader=False, threaded=True, host='127.0.0.1', port=$Port)
"@

Set-Content -LiteralPath $Runner -Value $runnerCode -Encoding UTF8

$process = Start-Process `
    -FilePath $Python `
    -ArgumentList "`"$Runner`"" `
    -WorkingDirectory $Root `
    -RedirectStandardOutput $OutFile `
    -RedirectStandardError $ErrFile `
    -WindowStyle Hidden `
    -PassThru

Set-Content -LiteralPath $PidFile -Value $process.Id -Encoding ASCII
Start-Sleep -Seconds 2

Write-Host "Bankroll Kings started on port $Port. PID: $($process.Id)"
Write-Host "Open: http://localhost:$Port/"
Write-Host "Stop it with: .\stop_server.ps1 -Port $Port"
