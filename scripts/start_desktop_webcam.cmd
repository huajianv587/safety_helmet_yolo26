@echo off
setlocal
cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
  echo Python virtual environment not found at .venv\Scripts\python.exe
  exit /b 1
)

set "YOLO_CONFIG_DIR=%CD%\.ultralytics"
set "HELMET_CONFIG_PATH=configs/runtime.desktop.json"

echo Starting dashboard container...
docker compose up -d dashboard
if errorlevel 1 exit /b 1

echo Dashboard URL: http://localhost:8501
echo Starting monitor on the Windows host with the laptop webcam...
echo Press Ctrl+C in this window to stop the webcam monitor.

.venv\Scripts\python.exe scripts\run_monitor.py
