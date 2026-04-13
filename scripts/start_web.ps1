param(
    [int]$Port = 8000,
    [switch]$Foreground
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RuntimeDir = Join-Path $ProjectRoot "data\runtime"
$LogDir = Join-Path $RuntimeDir "logs"
$PidFile = Join-Path $RuntimeDir "web.pid.json"

New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Get-PythonExe {
    $candidates = @(
        (Join-Path $ProjectRoot ".venv\Scripts\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe")
    )

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            try {
                & $candidate -c "import uvicorn" *> $null
                if ($LASTEXITCODE -eq 0) {
                    return $candidate
                }
            } catch {
            }
        }
    }

    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Path) {
        try {
            & $cmd.Path -c "import uvicorn" *> $null
            if ($LASTEXITCODE -eq 0) {
                return $cmd.Path
            }
        } catch {
        }
    }

    throw "Python executable with uvicorn installed was not found."
}

function Test-ExistingProcess {
    if (-not (Test-Path $PidFile)) {
        return $null
    }

    try {
        $payload = Get-Content $PidFile -Raw | ConvertFrom-Json
        $process = Get-Process -Id ([int]$payload.pid) -ErrorAction Stop
        return $process
    } catch {
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
        return $null
    }
}

function Get-PortProcessId {
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

function Write-PidFile {
    param(
        [int]$ProcessId,
        [string]$PythonPath,
        [string]$StdoutLog,
        [string]$StderrLog
    )

    $payload = @{
        pid = $ProcessId
        port = $Port
        started_at = (Get-Date).ToString("s")
        python = $PythonPath
        stdout_log = $StdoutLog
        stderr_log = $StderrLog
    } | ConvertTo-Json

    Set-Content -Path $PidFile -Value $payload -Encoding UTF8
}

$existing = Test-ExistingProcess
if ($existing) {
    Write-Output "AIcallorder web is already running with PID $($existing.Id)."
    exit 0
}

$pythonExe = Get-PythonExe
$stdoutLog = Join-Path $LogDir "uvicorn.stdout.log"
$stderrLog = Join-Path $LogDir "uvicorn.stderr.log"
$listenerPid = Get-PortProcessId
if ($listenerPid) {
    Write-PidFile -ProcessId $listenerPid -PythonPath $pythonExe -StdoutLog $stdoutLog -StderrLog $stderrLog
    Write-Output "AIcallorder web is already listening on http://127.0.0.1:$Port with PID $listenerPid."
    exit 0
}

$arguments = @(
    "-m", "uvicorn", "loom_automation.main:app",
    "--host", "127.0.0.1",
    "--port", "$Port"
)

if ($Foreground) {
    & $pythonExe @arguments
    exit $LASTEXITCODE
}

$process = Start-Process `
    -FilePath $pythonExe `
    -ArgumentList $arguments `
    -WorkingDirectory $ProjectRoot `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -WindowStyle Hidden `
    -PassThru

Start-Sleep -Seconds 2
if ($process.HasExited) {
    throw "AIcallorder web process exited immediately. Check logs in $LogDir."
}

Write-PidFile -ProcessId $process.Id -PythonPath $pythonExe -StdoutLog $stdoutLog -StderrLog $stderrLog

Write-Output "AIcallorder web started on http://127.0.0.1:$Port with PID $($process.Id)."
