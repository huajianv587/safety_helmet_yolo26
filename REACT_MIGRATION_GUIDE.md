# React前端迁移指南

## 📋 完整迁移步骤

### 1. 初始化项目

```bash
# 运行初始化脚本
bash init-react-frontend.sh

# 或手动执行
npx create-react-app frontend-react --template typescript
cd frontend-react
npm install @mui/material @emotion/react @emotion/styled
npm install react-router-dom axios socket.io-client
npm install recharts react-window date-fns
```

### 2. 复制模板文件

```bash
# 复制类型定义
cp react-templates/types.ts frontend-react/src/types/index.ts

# 复制Hooks
cp react-templates/useWebSocket.ts frontend-react/src/hooks/

# 复制组件
cp react-templates/Dashboard.tsx frontend-react/src/components/Dashboard/
cp react-templates/MetricCard.tsx frontend-react/src/components/Dashboard/
cp react-templates/AlertList.tsx frontend-react/src/components/Alerts/
```

### 3. 配置主题

创建 `src/theme.ts`:
```typescript
import { createTheme } from '@mui/material/styles';

export const theme = createTheme({
  palette: {
    mode: 'light',
    primary: {
      main: '#1976d2',
    },
    secondary: {
      main: '#dc004e',
    },
  },
  typography: {
    fontFamily: '"Inter", "Roboto", "Helvetica", "Arial", sans-serif',
  },
  components: {
    MuiCard: {
      styleOverrides: {
        root: {
          borderRadius: 12,
          boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
        },
      },
    },
  },
});
```

### 4. 更新App.tsx

```typescript
import React from 'react';
import { ThemeProvider } from '@mui/material/styles';
import { CssBaseline } from '@mui/material';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { theme } from './theme';
import Dashboard from './components/Dashboard/Dashboard';

function App() {
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Router>
        <Routes>
          <Route path="/" element={<Dashboard />} />
        </Routes>
      </Router>
    </ThemeProvider>
  );
}

export default App;
```

### 5. 配置代理

在 `package.json` 中添加:
```json
{
  "proxy": "http://localhost:8000"
}
```

### 6. 启动开发服务器

```bash
# 终端1: 启动后端
uvicorn helmet_monitoring.api.app:app --reload --port 8000

# 终端2: 启动React前端
cd frontend-react
npm start
```

## 🎨 组件清单

### 已提供的组件模板
- ✅ Dashboard.tsx - 仪表板主组件
- ✅ MetricCard.tsx - 指标卡片
- ✅ AlertList.tsx - 告警列表（虚拟滚动）
- ✅ useWebSocket.ts - WebSocket Hook
- ✅ types.ts - TypeScript类型定义

### 待实现的组件
- ⏳ CameraGrid.tsx - 摄像头网格
- ⏳ AlertDetail.tsx - 告警详情
- ⏳ Layout.tsx - 布局组件
- ⏳ Sidebar.tsx - 侧边栏
- ⏳ Header.tsx - 顶部栏

## 📊 性能优化清单

- ✅ 虚拟滚动（react-window）
- ✅ WebSocket实时更新
- ✅ 懒加载组件
- ✅ Material-UI优化
- ⏳ 代码分割
- ⏳ Service Worker
- ⏳ 图片懒加载

## 🚀 部署

### 开发环境
```bash
npm start
```

### 生产构建
```bash
npm run build
cp -r build/* ../frontend/
```

## 📝 注意事项

1. **WebSocket连接**: 确保后端WebSocket端点正常工作
2. **CORS配置**: 开发环境使用proxy，生产环境需配置CORS
3. **类型安全**: 所有API响应都应有对应的TypeScript类型
4. **错误处理**: 添加全局错误边界和错误提示
5. **加载状态**: 所有异步操作都应显示加载状态

## 🔗 相关文档

- [Material-UI文档](https://mui.com/)
- [React Router文档](https://reactrouter.com/)
- [React Window文档](https://react-window.vercel.app/)
- [WebSocket API文档](https://developer.mozilla.org/en-US/docs/Web/API/WebSocket)
