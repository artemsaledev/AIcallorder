$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PidFile = Join-Path $ProjectRoot "data\runtime\tunnel.pid.json"

if (-not (Test-Path $PidFile)) {
    Write-Output "Tunnel is not running."
    exit 0
}

try {
    $payload = Get-Content $PidFile -Raw | ConvertFrom-Json
    $pid = [int]$payload.pid
    Stop-Process -Id $pid -Force -ErrorAction Stop
    Write-Output "Stopped tunnel process $pid."
} catch {
    Write-Output "Tunnel process is not running anymore."
}

Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
