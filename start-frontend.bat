@echo off
REM Windows批处理脚本 - 启动前后端

echo ========================================
echo 🚀 启动 Safety Helmet Monitoring 系统
echo ========================================
echo.

REM 检查后端
echo 📡 检查后端服务...
curl -s http://localhost:8000/ >nul 2>&1
if %errorlevel% equ 0 (
    echo ✅ 后端已在运行 (http://localhost:8000)
) else (
    echo ⚠️  后端未运行
    echo.
    echo 请在新终端运行以下命令启动后端：
    echo cd e:\项目夹\safety_helmet_yolo26
    echo python -m src.helmet_monitoring.api.app
    echo.
)

REM 启动React前端
echo.
echo 🎨 启动React前端...
cd frontend-react

echo ✅ 使用端口: 3002
echo.
echo 前端将在以下地址打开：
echo http://localhost:3002
echo.
echo 按 Ctrl+C 停止服务器
echo ========================================
echo.

set PORT=3002
npm start
