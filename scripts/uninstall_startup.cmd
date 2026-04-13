@echo off
setlocal
set "TARGET=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\AIcallorder Web UI.cmd"

if exist "%TARGET%" (
  del "%TARGET%"
  echo Startup launcher removed: %TARGET%
) else (
  echo Startup launcher not found: %TARGET%
)
