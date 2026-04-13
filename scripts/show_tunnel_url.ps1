$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PidFile = Join-Path $ProjectRoot "data\runtime\tunnel.pid.json"

if (-not (Test-Path $PidFile)) {
    Write-Output "Tunnel is not running."
    exit 0
}

$payload = Get-Content $PidFile -Raw | ConvertFrom-Json
if ($payload.public_url) {
    Write-Output $payload.public_url
} else {
    Write-Output "Tunnel is running, but public URL is not saved yet. Check cloudflared logs."
}
