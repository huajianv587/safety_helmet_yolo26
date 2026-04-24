# React Frontend Quick Start Guide

## 🚀 Quick Start (3 Steps)

### Step 1: Install Dependencies (if not done)
```bash
cd frontend-react
npm install
```

### Step 2: Configure Environment
The `.env` file is already created with default settings:
```env
REACT_APP_API_URL=http://localhost:8000
REACT_APP_WS_URL=ws://localhost:8000/ws
```

### Step 3: Start Development Server
```bash
npm start
```

The app will automatically open at **http://localhost:3000**

## ✅ Verification Checklist

After starting, you should see:
- ✅ Dashboard loads successfully
- ✅ WebSocket shows "🟢 Connected" in top-right
- ✅ Metrics cards display system stats
- ✅ Alert list shows recent alerts
- ✅ Real-time updates when new alerts arrive

## 🔧 Troubleshooting

### Backend Not Running
If you see "🔴 Disconnected":
```bash
# Start the backend first
cd ..
python -m src.helmet_monitoring.api.app
```

### Port 3000 Already in Use
```bash
# Use a different port
PORT=3001 npm start
```

### Dependencies Missing
```bash
# Reinstall dependencies
rm -rf node_modules package-lock.json
npm install
```

## 📊 What You'll See

### Dashboard Features
1. **Top Bar**: Connection status, refresh button, notification badge
2. **Metrics Grid**: 8 real-time metric cards
   - Total/Active Cameras
   - Total/Critical Alerts
   - Detection Rate
   - CPU/Memory Usage
   - System Uptime
3. **Alert List**: Virtual scrolling list with severity badges
4. **System Status**: Right sidebar with key stats

### Real-time Updates
- New alerts appear instantly via WebSocket
- Metrics refresh every few seconds
- Trend indicators show changes (↑↓)
- Auto-reconnect if connection drops

## 🎨 UI Features

- **Responsive Design**: Works on desktop, tablet, mobile
- **Material Design**: Clean, modern UI components
- **Smooth Animations**: Card hover effects, transitions
- **Color-coded Alerts**: Critical (red), Warning (orange), Info (blue)
- **Virtual Scrolling**: Handles 1000+ alerts smoothly

## 🔄 Development Workflow

### Making Changes
1. Edit files in `src/`
2. Save - changes auto-reload
3. Check browser console for errors

### Adding New Components
```bash
# Create new component
mkdir -p src/components/NewFeature
touch src/components/NewFeature/NewFeature.tsx
```

### Testing API Calls
```typescript
import { alertsApi } from './services/api';

// Test in component
const testApi = async () => {
  const result = await alertsApi.getRecent(10);
  console.log(result);
};
```

## 📦 Build for Production

```bash
# Create optimized build
npm run build

# Output in build/ directory
# Serve with any static file server
npx serve -s build
```

## 🔗 Integration with Backend

The React app connects to:
- **REST API**: `http://localhost:8000/api/*`
- **WebSocket**: `ws://localhost:8000/ws`

Make sure backend is running with CORS enabled:
```python
# In app.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## 🎯 Next Development Steps

1. **Add Routing**: Install React Router for multi-page navigation
2. **Camera Page**: View and manage camera feeds
3. **Alert Review**: Acknowledge and filter alerts
4. **Settings Page**: Configure system parameters
5. **Dark Mode**: Theme switcher
6. **Charts**: Add time-series graphs with Recharts

## 📝 Notes

- Development server runs on port 3000
- Backend should run on port 8000
- WebSocket auto-reconnects if disconnected
- All API calls are typed with TypeScript
- Components use Material-UI for consistent styling

## 🆘 Need Help?

Check these files:
- `README.md` - Full documentation
- `src/services/api.ts` - API endpoints
- `src/hooks/useWebSocket.ts` - WebSocket logic
- `src/types/index.ts` - TypeScript types

Happy coding! 🎉
