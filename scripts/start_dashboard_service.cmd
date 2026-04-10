@echo off
setlocal
cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
  echo Python virtual environment not found at .venv\Scripts\python.exe
  exit /b 1
)

set "YOLO_CONFIG_DIR=%CD%\.ultralytics"
if not defined HELMET_CONFIG_PATH set "HELMET_CONFIG_PATH=configs/runtime.json"
if not defined HELMET_DASHBOARD_PORT set "HELMET_DASHBOARD_PORT=8501"

echo Starting managed dashboard service on port %HELMET_DASHBOARD_PORT% ...
echo This supervisor will auto-restart Streamlit if it exits or fails healthchecks.
echo.

.venv\Scripts\python.exe scripts\service_supervisor.py dashboard --config "%HELMET_CONFIG_PATH%" --dashboard-port %HELMET_DASHBOARD_PORT% %*
set "SERVICE_EXIT_CODE=%ERRORLEVEL%"
echo.
echo Dashboard service exited with code %SERVICE_EXIT_CODE%.
pause
exit /b %SERVICE_EXIT_CODE%
