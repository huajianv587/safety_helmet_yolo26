import React, { useEffect, useState } from 'react';
import {
  Box,
  Container,
  Grid,
  Paper,
  Typography,
  AppBar,
  Toolbar,
  IconButton,
  Badge,
} from '@mui/material';
import NotificationsIcon from '@mui/icons-material/Notifications';
import RefreshIcon from '@mui/icons-material/Refresh';
import MetricCard from './MetricCard';
import AlertList from '../Alerts/AlertList';
import { useWebSocket } from '../../hooks/useWebSocket';
import { alertsApi, metricsApi } from '../../services/api';
import { Alert, Metric, SystemStats } from '../../types';

const Dashboard: React.FC = () => {
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [systemStats, setSystemStats] = useState<SystemStats | null>(null);
  const [loading, setLoading] = useState(true);

  const WS_URL = process.env.REACT_APP_WS_URL || 'ws://localhost:8000/ws';

  const { isConnected, subscribe } = useWebSocket({
    url: WS_URL,
    onOpen: () => console.log('Connected to WebSocket'),
    onClose: () => console.log('Disconnected from WebSocket'),
  });

  // 加载初始数据
  const loadData = async () => {
    try {
      setLoading(true);
      const [alertsRes, statsRes] = await Promise.all([
        alertsApi.getRecent(50),
        metricsApi.getSystemStats(),
      ]);

      if (alertsRes.success && alertsRes.data) {
        setAlerts(alertsRes.data);
      }

      if (statsRes.success && statsRes.data) {
        setSystemStats(statsRes.data);
        updateMetrics(statsRes.data);
      }
    } catch (error) {
      console.error('Failed to load data:', error);
    } finally {
      setLoading(false);
    }
  };

  const updateMetrics = (stats: SystemStats) => {
    setMetrics([
      {
        name: 'Total Cameras',
        value: stats.total_cameras,
        unit: '',
        trend: 'stable',
      },
      {
        name: 'Active Cameras',
        value: stats.active_cameras,
        unit: '',
        trend: 'up',
        change: 5,
      },
      {
        name: 'Total Alerts',
        value: stats.total_alerts,
        unit: '',
        trend: 'down',
        change: -12,
      },
      {
        name: 'Critical Alerts',
        value: stats.critical_alerts,
        unit: '',
        trend: 'down',
        change: -8,
      },
      {
        name: 'Detection Rate',
        value: stats.detection_rate,
        unit: '%',
        trend: 'up',
        change: 3,
      },
      {
        name: 'CPU Usage',
        value: stats.cpu_usage,
        unit: '%',
        trend: 'stable',
      },
      {
        name: 'Memory Usage',
        value: stats.memory_usage,
        unit: '%',
        trend: 'stable',
      },
      {
        name: 'System Uptime',
        value: Math.floor(stats.system_uptime / 3600),
        unit: 'hrs',
        trend: 'up',
      },
    ]);
  };

  useEffect(() => {
    loadData();

    // 订阅WebSocket消息
    const unsubscribeAlert = subscribe('alert', (data: Alert) => {
      setAlerts((prev) => [data, ...prev].slice(0, 50));
    });

    const unsubscribeMetrics = subscribe('metrics', (data: SystemStats) => {
      setSystemStats(data);
      updateMetrics(data);
    });

    return () => {
      unsubscribeAlert();
      unsubscribeMetrics();
    };
  }, []);

  return (
    <Box sx={{ flexGrow: 1, bgcolor: 'background.default', minHeight: '100vh' }}>
      <AppBar position="static" elevation={1}>
        <Toolbar>
          <Typography variant="h6" component="div" sx={{ flexGrow: 1 }}>
            Safety Helmet Monitoring Dashboard
          </Typography>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Typography variant="body2" sx={{ mr: 2 }}>
              {isConnected ? '🟢 Connected' : '🔴 Disconnected'}
            </Typography>
            <IconButton color="inherit" onClick={loadData}>
              <RefreshIcon />
            </IconButton>
            <IconButton color="inherit">
              <Badge badgeContent={alerts.filter(a => !a.acknowledged).length} color="error">
                <NotificationsIcon />
              </Badge>
            </IconButton>
          </Box>
        </Toolbar>
      </AppBar>

      <Container maxWidth="xl" sx={{ mt: 4, mb: 4 }}>
        {/* 指标卡片 */}
        <Grid container spacing={3} sx={{ mb: 4 }}>
          {metrics.map((metric, index) => (
            <Grid size={{ xs: 12, sm: 6, md: 3 }} key={index}>
              <MetricCard metric={metric} loading={loading} />
            </Grid>
          ))}
        </Grid>

        {/* 告警列表 */}
        <Grid container spacing={3}>
          <Grid size={{ xs: 12, lg: 8 }}>
            <AlertList alerts={alerts} maxItems={100} />
          </Grid>

          {/* 系统状态 */}
          <Grid size={{ xs: 12, lg: 4 }}>
            <Paper sx={{ p: 3 }}>
              <Typography variant="h6" gutterBottom>
                System Status
              </Typography>
              {systemStats && (
                <Box sx={{ mt: 2 }}>
                  <Typography variant="body2" color="text.secondary" gutterBottom>
                    Uptime: {Math.floor(systemStats.system_uptime / 3600)}h {Math.floor((systemStats.system_uptime % 3600) / 60)}m
                  </Typography>
                  <Typography variant="body2" color="text.secondary" gutterBottom>
                    Active Cameras: {systemStats.active_cameras} / {systemStats.total_cameras}
                  </Typography>
                  <Typography variant="body2" color="text.secondary" gutterBottom>
                    Detection Rate: {systemStats.detection_rate}%
                  </Typography>
                </Box>
              )}
            </Paper>
          </Grid>
        </Grid>
      </Container>
    </Box>
  );
};

export default Dashboard;
