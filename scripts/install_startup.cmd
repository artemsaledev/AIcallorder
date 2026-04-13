@echo off
setlocal
set "PROJECT_ROOT=%~dp0.."
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "TARGET=%STARTUP_DIR%\AIcallorder Web UI.cmd"

> "%TARGET%" echo @echo off
>> "%TARGET%" echo powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_ROOT%\scripts\start_web.ps1"

echo Startup launcher created: %TARGET%
