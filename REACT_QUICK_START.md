# 🚀 React前端快速启动指南

## 一键启动（推荐）

### Windows
双击运行：
```
start-all.bat
```

这将自动启动：
- ✅ 后端API服务器 (http://localhost:8112)
- ✅ React前端开发服务器 (http://localhost:3002)
- ✅ 自动打开浏览器

---

## 手动启动

### 1. 启动后端API

```bash
# 方法A: 使用PYTHONPATH
cd e:/项目夹/safety_helmet_yolo26
set PYTHONPATH=src
python -m helmet_monitoring.api.app

# 方法B: 使用环境变量（Linux/Mac）
cd e:/项目夹/safety_helmet_yolo26
PYTHONPATH=src python -m helmet_monitoring.api.app
```

### 2. 启动React前端（新终端）

```bash
cd e:/项目夹/safety_helmet_yolo26/frontend-react
set PORT=3002
npm start
```

---

## 访问地址

启动成功后，访问以下地址：

| 服务 | 地址 | 说明 |
|------|------|------|
| **React UI** | http://localhost:3002 | 现代化React界面 |
| **后端API** | http://localhost:8112 | FastAPI后端服务 |
| **WebSocket** | ws://localhost:8112/ws | 实时数据推送 |
| **旧版UI** | http://localhost:8112 | 原始HTML界面 |

---

## 功能特性

### ✨ React前端特性

1. **实时仪表板**
   - 8个实时指标卡片
   - WebSocket实时更新
   - 连接状态指示器

2. **告警列表**
   - 虚拟滚动（支持1000+条）
   - 严重程度颜色编码
   - 时间戳自动格式化
   - 点击查看详情

3. **Material-UI设计**
   - 现代化UI组件
   - 响应式布局
   - 流畅动画效果

4. **性能优化**
   - 组件懒加载
   - 虚拟滚动
   - WebSocket自动重连
   - 请求去重

---

## 故障排除

### 问题1: 后端启动失败 - ModuleNotFoundError

**错误信息:**
```
ModuleNotFoundError: No module named 'helmet_monitoring'
```

**解决方案:**
```bash
# 确保设置了PYTHONPATH
set PYTHONPATH=src
python -m helmet_monitoring.api.app
```

---

### 问题2: 端口被占用

**错误信息:**
```
Error: listen EADDRINUSE: address already in use :::3002
```

**解决方案:**
```bash
# 方法A: 使用不同端口
set PORT=3003
npm start

# 方法B: 杀死占用进程（Windows）
netstat -ano | findstr :3002
taskkill /PID <进程ID> /F
```

---

### 问题3: WebSocket连接失败

**症状:** 界面显示 "🔴 Disconnected"

**检查清单:**
1. ✅ 后端是否运行在 http://localhost:8112
2. ✅ 检查 `.env` 文件中的 `REACT_APP_WS_URL`
3. ✅ 浏览器控制台是否有错误

**解决方案:**
```bash
# 检查后端是否运行
curl http://localhost:8112/api/v1/helmet/platform/overview

# 如果404，检查后端日志
cat backend.log
```

---

### 问题4: API请求失败

**症状:** 界面无数据显示

**检查:**
```bash
# 测试后端API
curl http://localhost:8000/api/v1/helmet/platform/overview

# 检查CORS配置
# 后端应该允许 http://localhost:3002
```

---

### 问题5: 编译错误

**错误信息:**
```
Module not found: Can't resolve '@mui/material'
```

**解决方案:**
```bash
cd frontend-react
rm -rf node_modules package-lock.json
npm install
```

---

## 开发模式

### 热重载

React开发服务器支持热重载：
- 修改 `.tsx` 或 `.ts` 文件会自动刷新
- 修改 `.css` 文件会自动注入
- 无需手动刷新浏览器

### 调试

**浏览器开发者工具:**
```
F12 或 右键 -> 检查
```

**React DevTools:**
安装Chrome扩展：[React Developer Tools](https://chrome.google.com/webstore/detail/react-developer-tools/fmkadmapgofadopljbjfkapdkoienihi)

**查看WebSocket消息:**
```javascript
// 在浏览器控制台
localStorage.setItem('debug', 'websocket')
```

---

## 性能监控

### 查看性能指标

打开浏览器控制台，输入：
```javascript
// 查看组件渲染时间
performance.getEntriesByType('measure')

// 查看网络请求
performance.getEntriesByType('resource')
```

### Lighthouse审计

```bash
# Chrome DevTools -> Lighthouse -> Generate Report
```

---

## 生产构建

### 构建优化版本

```bash
cd frontend-react
npm run build
```

构建产物在 `build/` 目录：
- 代码压缩
- Tree shaking
- 资源优化
- 生产环境配置

### 部署

```bash
# 使用静态文件服务器
npx serve -s build -p 3002

# 或使用Nginx
# 将 build/ 目录内容复制到 /var/www/html
```

---

## 环境变量

### `.env` 文件配置

```env
# API配置
REACT_APP_API_URL=http://localhost:8112
REACT_APP_WS_URL=ws://localhost:8112/ws

# 功能开关
REACT_APP_ENABLE_ANALYTICS=false
REACT_APP_DEBUG_MODE=true

# 性能配置
REACT_APP_CACHE_ENABLED=true
REACT_APP_VIRTUAL_SCROLL_ENABLED=true
```

---

## 技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| React | 19.2.5 | UI框架 |
| TypeScript | 4.9.5 | 类型安全 |
| Material-UI | 9.0.0 | UI组件库 |
| Axios | 1.15.2 | HTTP客户端 |
| React Window | 2.2.7 | 虚拟滚动 |
| Date-fns | 4.1.0 | 日期处理 |

---

## 下一步

### 推荐功能扩展

1. **路由导航**
   - 添加多页面支持
   - 摄像头管理页面
   - 告警详情页面

2. **高级功能**
   - 实时视频流查看
   - 告警过滤和搜索
   - 数据导出功能

3. **UI增强**
   - 深色模式
   - 国际化（中英文）
   - 自定义主题

4. **测试**
   - 单元测试（Jest）
   - E2E测试（Cypress）
   - 性能测试

---

## 获取帮助

### 文档
- [React官方文档](https://react.dev/)
- [Material-UI文档](https://mui.com/)
- [TypeScript文档](https://www.typescriptlang.org/)

### 项目文档
- `REACT_SETUP_COMPLETE.md` - 完整设置报告
- `frontend-react/README.md` - 项目README
- `OPTIMIZATION_ROADMAP.md` - 性能优化路线图

---

## 总结

✅ **已完成:**
- React + TypeScript项目搭建
- Material-UI集成
- WebSocket实时通信
- 虚拟滚动优化
- API服务层
- 一键启动脚本

🚀 **立即开始:**
```bash
# Windows
start-all.bat

# 然后访问
http://localhost:3002
```

享受现代化的React开发体验！
