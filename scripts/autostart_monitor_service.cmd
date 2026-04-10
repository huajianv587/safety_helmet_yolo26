@echo off
setlocal
cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" exit /b 1

set "YOLO_CONFIG_DIR=%CD%\.ultralytics"
if not defined HELMET_CONFIG_PATH set "HELMET_CONFIG_PATH=configs/runtime.json"

.venv\Scripts\python.exe scripts\service_supervisor.py monitor --config "%HELMET_CONFIG_PATH%"
exit /b %ERRORLEVEL%
