@echo off
setlocal
set "TARGET=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\AIcallorder Public Tunnel.cmd"

if exist "%TARGET%" (
  del "%TARGET%"
  echo Public tunnel startup launcher removed: %TARGET%
) else (
  echo Public tunnel startup launcher not found: %TARGET%
)
