$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PidFile = Join-Path $ProjectRoot "data\runtime\public-tunnel.pid.json"
$StdoutLog = Join-Path $ProjectRoot "data\runtime\logs\localtunnel.stdout.log"

if (Test-Path $PidFile) {
    $payload = Get-Content $PidFile -Raw | ConvertFrom-Json
    if ($payload.public_url) {
        Write-Output $payload.public_url
        exit 0
    }
}

if (Test-Path $StdoutLog) {
    $text = Get-Content $StdoutLog -Raw -ErrorAction SilentlyContinue
    $matches = [regex]::Matches($text, 'https://[A-Za-z0-9\-]+\.loca\.lt')
    if ($matches.Count -gt 0) {
        Write-Output $matches[$matches.Count - 1].Value
        exit 0
    }
}

Write-Output "Public tunnel is not running."
