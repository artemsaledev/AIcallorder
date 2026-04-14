$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PidFile = Join-Path $ProjectRoot "data\runtime\public-tunnel.pid.json"

function Stop-MatchingTunnelProcesses {
    $matched = Get-CimInstance Win32_Process |
        Where-Object {
            ($_.Name -eq 'node.exe' -and $_.CommandLine -match 'localtunnel|lt\.js') -or
            ($_.Name -eq 'cmd.exe' -and $_.CommandLine -match 'localtunnel|\blt\b')
        }

    if (-not $matched) {
        return $false
    }

    foreach ($proc in $matched) {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    }
    return $true
}

if (-not (Test-Path $PidFile)) {
    if (Stop-MatchingTunnelProcesses) {
        Write-Output "Stopped public tunnel processes."
    } else {
        Write-Output "Public tunnel is not running."
    }
    exit 0
}

try {
    $payload = Get-Content $PidFile -Raw | ConvertFrom-Json
    Stop-Process -Id ([int]$payload.pid) -Force -ErrorAction Stop
    Write-Output "Stopped public tunnel process $($payload.pid)."
} catch {
    if (Stop-MatchingTunnelProcesses) {
        Write-Output "Stopped public tunnel processes."
    } else {
        Write-Output "Public tunnel process is not running anymore."
    }
}

Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
