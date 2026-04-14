param(
    [int]$LocalPort = 8000
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RuntimeDir = Join-Path $ProjectRoot "data\runtime"
$LogDir = Join-Path $RuntimeDir "logs"
$PidFile = Join-Path $RuntimeDir "public-tunnel.pid.json"
$StdoutLog = Join-Path $LogDir "localtunnel.stdout.log"
$StderrLog = Join-Path $LogDir "localtunnel.stderr.log"
$TargetUrl = "http://127.0.0.1:$LocalPort"
$HealthUrl = "$TargetUrl/health"

New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Wait-LocalWeb {
    for ($i = 0; $i -lt 60; $i++) {
        try {
            $response = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -eq 200) {
                return $true
            }
        } catch {
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Read-PidPayload {
    if (-not (Test-Path $PidFile)) {
        return $null
    }

    try {
        return Get-Content $PidFile -Raw | ConvertFrom-Json
    } catch {
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
        return $null
    }
}

function Write-PidPayload {
    param(
        [int]$ProcessId,
        [string]$PublicUrl
    )

    $payload = @{
        pid = $ProcessId
        local_url = $TargetUrl
        public_url = $PublicUrl
        stdout_log = $StdoutLog
        stderr_log = $StderrLog
        started_at = (Get-Date).ToString("s")
    } | ConvertTo-Json

    Set-Content -Path $PidFile -Value $payload -Encoding UTF8
}

function Get-NodeIds {
    @(Get-Process node -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
}

$existing = Read-PidPayload
if ($existing) {
    try {
        $proc = Get-Process -Id ([int]$existing.pid) -ErrorAction Stop
        $existingUrl = "url-pending"
        if ($existing.public_url) {
            $existingUrl = $existing.public_url
        }
        Write-Output ("Public tunnel is already running: " + $existingUrl)
        exit 0
    } catch {
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    }
}

if (-not (Wait-LocalWeb)) {
    throw "Local web app is not responding on $HealthUrl"
}

if (Test-Path $StdoutLog) { Remove-Item $StdoutLog -Force -ErrorAction SilentlyContinue }
if (Test-Path $StderrLog) { Remove-Item $StderrLog -Force -ErrorAction SilentlyContinue }

$beforeNodeIds = Get-NodeIds
$process = Start-Process `
    -FilePath "cmd.exe" `
    -ArgumentList "/c", "npx --yes localtunnel --port $LocalPort" `
    -WorkingDirectory $ProjectRoot `
    -RedirectStandardOutput $StdoutLog `
    -RedirectStandardError $StderrLog `
    -WindowStyle Hidden `
    -PassThru

Start-Sleep -Seconds 3
if ($process.HasExited) {
    throw "localtunnel exited immediately. Check $StderrLog"
}

$publicUrl = ""
for ($i = 0; $i -lt 45; $i++) {
    $text = ""
    if (Test-Path $StdoutLog) {
        $text += Get-Content $StdoutLog -Raw -ErrorAction SilentlyContinue
    }
    if ($text -match 'https://[A-Za-z0-9\-]+\.loca\.lt') {
        $publicUrl = $Matches[0]
        break
    }
    Start-Sleep -Seconds 1
}

$afterNodeIds = Get-NodeIds
$newNodeId = $null
foreach ($id in $afterNodeIds) {
    if ($beforeNodeIds -notcontains $id) {
        $newNodeId = $id
        break
    }
}

$savedPid = $process.Id
if ($newNodeId) {
    $savedPid = [int]$newNodeId
}

Write-PidPayload -ProcessId $savedPid -PublicUrl $publicUrl

if ($publicUrl) {
    Write-Output "Public tunnel started: $publicUrl"
} else {
    Write-Output "Public tunnel process started, but URL is still pending. Check logs."
}
