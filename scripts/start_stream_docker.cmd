@echo off
setlocal
cd /d "%~dp0\.."

set "YOLO_CONFIG_DIR=%CD%\.ultralytics"

if not exist ".venv\Scripts\python.exe" (
  echo Python virtual environment not found at .venv\Scripts\python.exe
  exit /b 1
)

for /f "usebackq delims=" %%A in (`.venv\Scripts\python.exe -c "from dotenv import dotenv_values; values=dotenv_values('.env'); print((values.get('HELMET_MONITOR_STREAM_URL') or '').strip())"`) do set "HELMET_MONITOR_STREAM_URL_VALUE=%%A"
for /f "usebackq delims=" %%A in (`.venv\Scripts\python.exe -c "from dotenv import dotenv_values; values=dotenv_values('.env'); print((values.get('HELMET_PUBLISH_URL') or '').strip())"`) do set "HELMET_PUBLISH_URL_VALUE=%%A"

if "%HELMET_MONITOR_STREAM_URL_VALUE%"=="" (
  echo HELMET_MONITOR_STREAM_URL is empty in .env
  echo Fill it with the Docker-side stream source URL, then run this script again.
  exit /b 1
)

echo Docker monitor source: %HELMET_MONITOR_STREAM_URL_VALUE%

echo %HELMET_MONITOR_STREAM_URL_VALUE% | findstr /i /c:"rtmp-gateway" >nul
if not errorlevel 1 (
  if "%HELMET_PUBLISH_URL_VALUE%"=="" (
    echo HELMET_PUBLISH_URL is empty in .env
    echo Fill it with the host-side RTMP publish target for your phone app, then run this script again.
    exit /b 1
  )
  echo Phone publish target: %HELMET_PUBLISH_URL_VALUE%
) else (
  echo Direct pull mode is active. The phone app should expose this exact source URL to the monitor.
)

echo Dashboard URL after startup: http://localhost:8501

docker compose up -d --build
