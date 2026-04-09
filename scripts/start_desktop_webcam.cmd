@echo off
setlocal
cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
  echo Python virtual environment not found at .venv\Scripts\python.exe
  exit /b 1
)

set "YOLO_CONFIG_DIR=%CD%\.ultralytics"
set "HELMET_CONFIG_PATH=configs/runtime.json"

echo Starting lightweight browser camera preview...
echo This avoids the heavy dashboard page and does not start the old host monitor.
echo A browser tab will open automatically after the preview server starts.
echo.

.venv\Scripts\python.exe scripts\browser_camera_preview.py %*
set "PREVIEW_EXIT_CODE=%ERRORLEVEL%"
echo.
echo Preview exited with code %PREVIEW_EXIT_CODE%.
pause
exit /b %PREVIEW_EXIT_CODE%
