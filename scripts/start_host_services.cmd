@echo off
setlocal
cd /d "%~dp0\.."

if not defined HELMET_DASHBOARD_PORT set "HELMET_DASHBOARD_PORT=8501"
set "HELMET_DASHBOARD_URL=http://localhost:%HELMET_DASHBOARD_PORT%"

echo Launching managed dashboard and monitor services in separate windows...
start "Helmet Dashboard Service" cmd /k ""%CD%\scripts\start_dashboard_service.cmd""
start "Helmet Monitor Service" cmd /k ""%CD%\scripts\start_monitor_service.cmd""
start "Helmet Dashboard Browser" powershell -NoProfile -Command "Start-Sleep -Seconds 2; Start-Process '%HELMET_DASHBOARD_URL%'"

echo.
echo Dashboard UI: %HELMET_DASHBOARD_URL%
echo A browser tab will open automatically after the services start.
echo Service logs:
echo   artifacts\runtime\services\dashboard_service.log
echo   artifacts\runtime\services\monitor_service.log
