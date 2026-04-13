$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PidFile = Join-Path $ProjectRoot "data\runtime\web.pid.json"
$Port = 8000

function Get-ListenerProcessId {
    try {
        $connection = Get-NetTCPConnection -LocalAddress "127.0.0.1" -LocalPort $Port -State Listen -ErrorAction Stop |
            Select-Object -First 1
        if ($connection) {
            return [int]$connection.OwningProcess
        }
    } catch {
    }
    return $null
}

if (-not (Test-Path $PidFile)) {
    $listenerPid = Get-ListenerProcessId
    if ($listenerPid) {
        Stop-Process -Id $listenerPid -Force -ErrorAction SilentlyContinue
        Write-Output "Stopped AIcallorder web listener process $listenerPid."
        exit 0
    }
    Write-Output "AIcallorder web is not running."
    exit 0
}

try {
    $payload = Get-Content $PidFile -Raw | ConvertFrom-Json
    $pid = [int]$payload.pid
    $process = Get-Process -Id $pid -ErrorAction Stop
    Stop-Process -Id $pid -Force
    Write-Output "Stopped AIcallorder web process $pid."
} catch {
    $listenerPid = Get-ListenerProcessId
    if ($listenerPid) {
        Stop-Process -Id $listenerPid -Force -ErrorAction SilentlyContinue
        Write-Output "Stopped AIcallorder web listener process $listenerPid."
    } else {
        Write-Output "Process from PID file is not running anymore."
    }
}

Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
