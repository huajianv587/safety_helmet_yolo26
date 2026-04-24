# Safety Helmet Monitoring - React Frontend

Modern React + TypeScript frontend for the Safety Helmet Monitoring System.

## Features

- **Real-time Dashboard**: Live metrics and alerts via WebSocket
- **Material-UI Design**: Modern, responsive UI components
- **TypeScript**: Full type safety and IntelliSense support
- **Virtual Scrolling**: Optimized performance for large alert lists
- **Auto-reconnect**: Robust WebSocket connection management

## Tech Stack

- React 19.2.5
- TypeScript 4.9.5
- Material-UI 9.0.0
- Axios for API calls
- React Window for virtualization
- Recharts for data visualization

## Getting Started

### Installation

```bash
npm install
```

### Start Development Server

```bash
npm start
```

Opens at http://localhost:3000

### Environment Variables

`.env` file (already configured):
```env
REACT_APP_API_URL=http://localhost:8000
REACT_APP_WS_URL=ws://localhost:8000/ws
```

## Available Scripts

- `npm start` - Development server (port 3000)
- `npm build` - Production build
- `npm test` - Run tests

## Project Structure

```
src/
├── components/
│   ├── Dashboard/        # Main dashboard
│   └── Alerts/          # Alert list
├── hooks/               # Custom hooks
├── services/            # API layer
├── types/               # TypeScript types
└── App.tsx             # Root component
```

## Key Features

### Dashboard
Real-time metrics with WebSocket updates

### Virtual Scrolling
Handles 1000+ alerts smoothly

### Auto-reconnect
Robust WebSocket with exponential backoff

## API Integration

```typescript
import { alertsApi } from './services/api';
const alerts = await alertsApi.getRecent(50);
```

## Troubleshooting

- Ensure backend runs on port 8000
- Check WebSocket URL in `.env`
- Clear cache: `rm -rf node_modules && npm install`

## License

MIT
