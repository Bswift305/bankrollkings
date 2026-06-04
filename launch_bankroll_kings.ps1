param(
    [int]$Port = 5000
)

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Url = "http://localhost:$Port/"
$StartScript = Join-Path $Root "start_server.ps1"

function Test-BankrollServer {
    param([int]$TargetPort)
    $client = $null
    try {
        $client = [System.Net.Sockets.TcpClient]::new()
        $connect = $client.BeginConnect("127.0.0.1", $TargetPort, $null, $null)
        $success = $connect.AsyncWaitHandle.WaitOne(1000, $false)
        if (-not $success) {
            return $false
        }
        $client.EndConnect($connect)
        return $true
    } catch {
        return $false
    } finally {
        if ($client) {
            $client.Close()
        }
    }
}

Set-Location $Root

if (-not (Test-BankrollServer -TargetPort $Port)) {
    Write-Host "Starting Bankroll Kings on port $Port..."
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $StartScript -Port $Port
} else {
    Write-Host "Bankroll Kings is already running on port $Port."
}

$ready = $false
for ($i = 1; $i -le 30; $i++) {
    if (Test-BankrollServer -TargetPort $Port) {
        $ready = $true
        break
    }
    Start-Sleep -Seconds 1
}

if (-not $ready) {
    Write-Host "Server did not answer within 30 seconds. Check .runtime logs."
    exit 1
}

Write-Host "Opening $Url"
Start-Process $Url
