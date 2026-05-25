param(
    [int]$Port = 5000
)

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunDir = Join-Path $Root '.runtime'
$Runner = Join-Path $RunDir "run_bankroll_flask_$Port.py"
$PidFile = Join-Path $RunDir "server_$Port.pid"

$targets = @()

if (Test-Path -LiteralPath $PidFile) {
    $pidText = (Get-Content -LiteralPath $PidFile -Raw).Trim()
    if ($pidText -match '^\d+$') {
        $pidProcess = Get-Process -Id ([int]$pidText) -ErrorAction SilentlyContinue
        if ($pidProcess) {
            $targets += $pidProcess
        }
    }
}

$matched = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match 'python' -and
    (
        $_.CommandLine -match [regex]::Escape($Runner) -or
        ($_.CommandLine -match 'run_bankroll_flask' -and $_.CommandLine -match "_$Port\.py")
    )
}

foreach ($proc in $matched) {
    $process = Get-Process -Id $proc.ProcessId -ErrorAction SilentlyContinue
    if ($process) {
        $targets += $process
    }
}

$targets = $targets | Sort-Object Id -Unique

if (-not $targets) {
    if (Test-Path -LiteralPath $PidFile) {
        Remove-Item -LiteralPath $PidFile -Force
    }
    Write-Host "No Bankroll Kings server found on port $Port."
    exit 0
}

foreach ($process in $targets) {
    Stop-Process -Id $process.Id -Force
    Write-Host "Stopped Bankroll Kings server PID $($process.Id) on port $Port."
}

if (Test-Path -LiteralPath $PidFile) {
    Remove-Item -LiteralPath $PidFile -Force
}
