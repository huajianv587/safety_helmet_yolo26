@echo off
setlocal
cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
  echo Python virtual environment not found at .venv\Scripts\python.exe
  exit /b 1
)

set "YOLO_CONFIG_DIR=%CD%\.ultralytics"
if not defined HELMET_CONFIG_PATH set "HELMET_CONFIG_PATH=configs/runtime.json"

echo Starting managed monitor service...
echo This supervisor will auto-restart the monitor if it exits or misses healthchecks.
echo.

.venv\Scripts\python.exe scripts\service_supervisor.py monitor --config "%HELMET_CONFIG_PATH%" %*
set "SERVICE_EXIT_CODE=%ERRORLEVEL%"
echo.
echo Monitor service exited with code %SERVICE_EXIT_CODE%.
pause
exit /b %SERVICE_EXIT_CODE%
