@echo off
setlocal

set "REPO_ROOT=%~dp0"
if "%REPO_ROOT:~-1%"=="\" set "REPO_ROOT=%REPO_ROOT:~0,-1%"
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

if not defined HELMET_DASHBOARD_TASK_NAME set "HELMET_DASHBOARD_TASK_NAME=SafetyHelmetDashboard"
if not defined HELMET_MONITOR_TASK_NAME set "HELMET_MONITOR_TASK_NAME=SafetyHelmetMonitor"
if not defined HELMET_CONFIG_PATH set "HELMET_CONFIG_PATH=configs/runtime.json"
if not defined HELMET_DASHBOARD_PORT set "HELMET_DASHBOARD_PORT=8501"

set "DASHBOARD_CMD=%REPO_ROOT%\scripts\autostart_dashboard_service.cmd"
set "MONITOR_CMD=%REPO_ROOT%\scripts\autostart_monitor_service.cmd"

call :create_task "%HELMET_DASHBOARD_TASK_NAME%" "%DASHBOARD_CMD%"
if errorlevel 1 (
  if not exist "%STARTUP_DIR%" mkdir "%STARTUP_DIR%" >nul 2>nul
  > "%STARTUP_DIR%\%HELMET_DASHBOARD_TASK_NAME%.cmd" (
    echo @echo off
    echo setlocal
    echo set "HELMET_CONFIG_PATH=%HELMET_CONFIG_PATH%"
    echo set "HELMET_DASHBOARD_PORT=%HELMET_DASHBOARD_PORT%"
    echo call "%REPO_ROOT%\scripts\autostart_dashboard_service.cmd"
  )
  if not exist "%STARTUP_DIR%\%HELMET_DASHBOARD_TASK_NAME%.cmd" exit /b 1
  echo created_startup_launcher=%STARTUP_DIR%\%HELMET_DASHBOARD_TASK_NAME%.cmd
)

call :create_task "%HELMET_MONITOR_TASK_NAME%" "%MONITOR_CMD%"
if errorlevel 1 (
  if not exist "%STARTUP_DIR%" mkdir "%STARTUP_DIR%" >nul 2>nul
  > "%STARTUP_DIR%\%HELMET_MONITOR_TASK_NAME%.cmd" (
    echo @echo off
    echo setlocal
    echo set "HELMET_CONFIG_PATH=%HELMET_CONFIG_PATH%"
    echo call "%REPO_ROOT%\scripts\autostart_monitor_service.cmd"
  )
  if not exist "%STARTUP_DIR%\%HELMET_MONITOR_TASK_NAME%.cmd" exit /b 1
  echo created_startup_launcher=%STARTUP_DIR%\%HELMET_MONITOR_TASK_NAME%.cmd
)

echo dashboard_task=%HELMET_DASHBOARD_TASK_NAME%
echo monitor_task=%HELMET_MONITOR_TASK_NAME%
echo startup_mode=AtLogOn_or_StartupFallback
echo repo_root=%REPO_ROOT%
echo config_path=%HELMET_CONFIG_PATH%
echo dashboard_port=%HELMET_DASHBOARD_PORT%
exit /b 0

:create_task
setlocal
set "TASK_NAME=%~1"
set "TASK_COMMAND=%~2"
schtasks /Create /TN "%TASK_NAME%" /SC ONLOGON /RL HIGHEST /TR "%TASK_COMMAND%" /F >nul 2>nul
if errorlevel 1 (
  schtasks /Create /TN "%TASK_NAME%" /SC ONLOGON /TR "%TASK_COMMAND%" /F >nul 2>nul
  if errorlevel 1 (
    endlocal & echo failed_task=%~1 startup_fallback=enabled & exit /b 1
  )
  endlocal & echo created_task=%~1 run_level=limited & exit /b 0
)
endlocal & echo created_task=%~1 run_level=highest & exit /b 0
