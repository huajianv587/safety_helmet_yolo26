#!/bin/bash
# 完整的前后端启动脚本

echo "🚀 启动 Safety Helmet Monitoring 系统"
echo "======================================"

# 检查后端是否运行
echo ""
echo "📡 检查后端服务..."
if curl -s http://localhost:8000/ > /dev/null 2>&1; then
    echo "✅ 后端已在运行 (http://localhost:8000)"
else
    echo "⚠️  后端未运行，正在启动..."
    echo ""
    echo "请在新终端运行以下命令启动后端："
    echo "cd e:\\项目夹\\safety_helmet_yolo26"
    echo "python -m src.helmet_monitoring.api.app"
    echo ""
fi

# 启动React前端
echo ""
echo "🎨 启动React前端..."
cd frontend-react

# 查找可用端口
PORT=3002
while lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1 ; do
    echo "端口 $PORT 被占用，尝试 $((PORT+1))..."
    PORT=$((PORT+1))
done

echo "✅ 使用端口: $PORT"
echo ""
echo "前端将在以下地址打开："
echo "http://localhost:$PORT"
echo ""
echo "按 Ctrl+C 停止服务器"
echo "======================================"

PORT=$PORT npm start
