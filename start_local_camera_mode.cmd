@echo off
setlocal
cd /d "%~dp0"

set "camera_use_laptop_camera=true"
set "CAMERA_USE_LAPTOP_CAMERA=true"
if not defined HELMET_API_PORT set "HELMET_API_PORT=8001"
if not defined HELMET_LIVE_PREVIEW_PORT set "HELMET_LIVE_PREVIEW_PORT=8876"

echo Starting Safety Helmet local camera mode...
echo.
echo App:     http://127.0.0.1:%HELMET_API_PORT%/app/#/cameras
echo Preview: http://127.0.0.1:%HELMET_LIVE_PREVIEW_PORT%/browser/cam-local-001
echo.

start "Safety Helmet API" cmd /k "cd /d \"%~dp0\" && set camera_use_laptop_camera=true && set CAMERA_USE_LAPTOP_CAMERA=true && call start_api_server.cmd"
start "Safety Helmet Browser Camera Preview" cmd /k "cd /d \"%~dp0\" && set camera_use_laptop_camera=true && set CAMERA_USE_LAPTOP_CAMERA=true && call start_desktop_webcam.cmd --no-browser"

echo Two windows were launched:
echo 1. API + SPA
echo 2. Browser local camera preview
echo.
echo Open the URLs above after both windows finish starting.
