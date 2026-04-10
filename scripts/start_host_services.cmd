@echo off
setlocal
cd /d "%~dp0\.."

echo Launching managed dashboard and monitor services in separate windows...
start "Helmet Dashboard Service" cmd /k ""%CD%\scripts\start_dashboard_service.cmd""
start "Helmet Monitor Service" cmd /k ""%CD%\scripts\start_monitor_service.cmd""

echo.
echo Dashboard UI: http://localhost:8501
echo Service logs:
echo   artifacts\runtime\services\dashboard_service.log
echo   artifacts\runtime\services\monitor_service.log
