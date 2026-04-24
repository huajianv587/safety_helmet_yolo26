@echo off
echo ========================================
echo Starting Safety Helmet Monitoring System
echo ========================================
echo.

echo [1/2] Starting Backend API Server...
start "Backend API" cmd /k "cd /d %~dp0 && set PYTHONPATH=src && python -m helmet_monitoring.api.app"
timeout /t 3 /nobreak >nul

echo [2/2] Starting React Frontend...
start "React Frontend" cmd /k "cd /d %~dp0frontend-react && set PORT=3002 && npm start"

echo.
echo ========================================
echo Services Starting...
echo ========================================
echo Backend API:  http://localhost:8112
echo React UI:     http://localhost:3002
echo WebSocket:    ws://localhost:8112/ws
echo ========================================
echo.
echo Press any key to open React UI in browser...
pause >nul
start http://localhost:3002
