@echo off
setlocal
cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
  echo Python virtual environment not found at .venv\Scripts\python.exe
  exit /b 1
)

set "YOLO_CONFIG_DIR=%CD%\.ultralytics"
set "HELMET_CONFIG_PATH=configs/runtime.json"

echo Starting the real-time webcam viewer on camera 0...
echo Close the viewer window or press Esc / q to stop.

.venv\Scripts\python.exe scripts\realtime_camera_viewer.py --source 0
set "VIEWER_EXIT_CODE=%ERRORLEVEL%"
echo.
echo Viewer exited with code %VIEWER_EXIT_CODE%.
pause
exit /b %VIEWER_EXIT_CODE%
