param(
    [int]$LocalPort = 8000
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RuntimeDir = Join-Path $ProjectRoot "data\runtime"
$LogDir = Join-Path $RuntimeDir "logs"
$PidFile = Join-Path $RuntimeDir "tunnel.pid.json"
$CloudflaredExe = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
$TargetUrl = "http://127.0.0.1:$LocalPort"

New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

if (-not (Test-Path $CloudflaredExe)) {
    throw "cloudflared executable not found at $CloudflaredExe"
}

function Write-TunnelPidFile {
    param(
        [int]$ProcessId,
        [string]$PublicUrl,
        [string]$StdoutLog,
        [string]$StderrLog
    )

    $payload = @{
        pid = $ProcessId
        local_url = $TargetUrl
        public_url = $PublicUrl
        started_at = (Get-Date).ToString("s")
        stdout_log = $StdoutLog
        stderr_log = $StderrLog
        executable = $CloudflaredExe
    } | ConvertTo-Json

    Set-Content -Path $PidFile -Value $payload -Encoding UTF8
}

if (Test-Path $PidFile) {
    try {
        $payload = Get-Content $PidFile -Raw | ConvertFrom-Json
        $process = Get-Process -Id ([int]$payload.pid) -ErrorAction Stop
        Write-Output "Tunnel is already running: $($payload.public_url)"
        exit 0
    } catch {
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    }
}

$stdoutLog = Join-Path $LogDir "cloudflared.stdout.log"
$stderrLog = Join-Path $LogDir "cloudflared.stderr.log"

$process = Start-Process `
    -FilePath $CloudflaredExe `
    -ArgumentList @("tunnel", "--url", $TargetUrl, "--no-autoupdate") `
    -WorkingDirectory $ProjectRoot `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -WindowStyle Hidden `
    -PassThru

Start-Sleep -Seconds 2
if ($process.HasExited) {
    throw "cloudflared exited immediately. Check $stderrLog"
}

$publicUrl = $null
for ($i = 0; $i -lt 30; $i++) {
    $logText = ""
    if (Test-Path $stdoutLog) {
        $logText += Get-Content $stdoutLog -Raw -ErrorAction SilentlyContinue
    }
    if (Test-Path $stderrLog) {
        $logText += "`n" + (Get-Content $stderrLog -Raw -ErrorAction SilentlyContinue)
    }
    $match = [regex]::Match($logText, 'https://[-a-z0-9]+\.trycloudflare\.com')
    if ($match.Success) {
        $publicUrl = $match.Value
        break
    }
    Start-Sleep -Seconds 1
}

$savedPublicUrl = ""
if ($publicUrl) {
    $savedPublicUrl = $publicUrl
}

Write-TunnelPidFile -ProcessId $process.Id -PublicUrl $savedPublicUrl -StdoutLog $stdoutLog -StderrLog $stderrLog

if ($publicUrl) {
    Write-Output "Tunnel started: $publicUrl"
} else {
    Write-Output "Tunnel process started with PID $($process.Id), but public URL was not detected yet. Check logs."
}
