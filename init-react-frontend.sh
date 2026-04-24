#!/bin/bash
# React前端初始化脚本

echo "🚀 开始初始化React前端项目..."

# 创建React项目
echo "📦 创建React + TypeScript项目..."
npx create-react-app frontend-react --template typescript

cd frontend-react

# 安装核心依赖
echo "📦 安装Material-UI..."
npm install @mui/material @emotion/react @emotion/styled @mui/icons-material

echo "📦 安装路由和状态管理..."
npm install react-router-dom @types/react-router-dom

echo "📦 安装WebSocket客户端..."
npm install socket.io-client @types/socket.io-client

echo "📦 安装HTTP客户端..."
npm install axios

echo "📦 安装图表库..."
npm install recharts

echo "📦 安装虚拟滚动..."
npm install react-window @types/react-window

echo "📦 安装日期处理..."
npm install date-fns

echo "📦 安装开发工具..."
npm install --save-dev @types/node

echo "✅ 依赖安装完成！"

# 创建目录结构
echo "📁 创建项目目录结构..."
mkdir -p src/components/Dashboard
mkdir -p src/components/Alerts
mkdir -p src/components/Cameras
mkdir -p src/components/Common
mkdir -p src/hooks
mkdir -p src/services
mkdir -p src/store
mkdir -p src/types
mkdir -p src/utils

echo "✅ 目录结构创建完成！"

echo ""
echo "🎉 React前端项目初始化完成！"
echo ""
echo "下一步："
echo "1. cd frontend-react"
echo "2. npm start"
echo ""
echo "开发服务器将在 http://localhost:3000 启动"
