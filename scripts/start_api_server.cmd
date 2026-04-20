@echo off
setlocal
cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
  echo Python virtual environment not found at .venv\Scripts\python.exe
  exit /b 1
)

set "PYTHONPATH=%CD%\src"
set "YOLO_CONFIG_DIR=%CD%\.ultralytics"
if not defined HELMET_API_PORT set "HELMET_API_PORT=8000"
if not defined HELMET_CONFIG_PATH set "HELMET_CONFIG_PATH=configs/runtime.json"

echo Starting Safety Helmet API and static frontend on http://127.0.0.1:%HELMET_API_PORT% ...
echo Old Streamlit dashboard remains available through start_dashboard_service.cmd.
echo.

.venv\Scripts\python.exe scripts\run_api_server.py
set "SERVICE_EXIT_CODE=%ERRORLEVEL%"
echo.
echo API service exited with code %SERVICE_EXIT_CODE%.
pause
exit /b %SERVICE_EXIT_CODE%
