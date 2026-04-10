@echo off
setlocal

if not defined HELMET_DASHBOARD_TASK_NAME set "HELMET_DASHBOARD_TASK_NAME=SafetyHelmetDashboard"
if not defined HELMET_MONITOR_TASK_NAME set "HELMET_MONITOR_TASK_NAME=SafetyHelmetMonitor"
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

for %%T in ("%HELMET_DASHBOARD_TASK_NAME%" "%HELMET_MONITOR_TASK_NAME%") do (
  schtasks /Delete /TN %%~T /F >nul 2>nul
  if errorlevel 1 (
    echo missing_task=%%~T
  ) else (
    echo removed_task=%%~T
  )
)

for %%F in ("%STARTUP_DIR%\%HELMET_DASHBOARD_TASK_NAME%.cmd" "%STARTUP_DIR%\%HELMET_MONITOR_TASK_NAME%.cmd") do (
  if exist "%%~F" (
    del /f /q "%%~F" >nul 2>nul
    if exist "%%~F" (
      echo failed_launcher_remove=%%~F
    ) else (
      echo removed_launcher=%%~F
    )
  ) else (
    echo missing_launcher=%%~F
  )
)
