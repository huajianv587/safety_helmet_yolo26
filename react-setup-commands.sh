#!/bin/bash
# React项目完整设置脚本

echo "📦 安装依赖..."
cd frontend-react

# 核心依赖
npm install @mui/material @emotion/react @emotion/styled
npm install @mui/icons-material
npm install react-router-dom
npm install axios
npm install socket.io-client
npm install recharts
npm install react-window
npm install date-fns

# 开发依赖
npm install -D @types/react-window
npm install -D tailwindcss postcss autoprefixer

echo "✅ 依赖安装完成"

# 初始化Tailwind CSS
npx tailwindcss init -p

echo "📁 创建目录结构..."
mkdir -p src/components/Dashboard
mkdir -p src/components/Alerts
mkdir -p src/components/Camera
mkdir -p src/components/Layout
mkdir -p src/hooks
mkdir -p src/types
mkdir -p src/services
mkdir -p src/utils

echo "✅ 目录结构创建完成"
echo "🎉 React项目设置完成！"
echo ""
echo "下一步："
echo "1. 复制模板文件到对应目录"
echo "2. 运行 npm start 启动开发服务器"
