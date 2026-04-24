// src/components/Dashboard/Dashboard.tsx
// 仪表板主组件

import React, { useEffect, useState } from 'react';
import {
  Grid,
  Card,
  CardContent,
  Typography,
  Box,
  CircularProgress,
} from '@mui/material';
import {
  TrendingUp as TrendingUpIcon,
  Warning as WarningIcon,
  Videocam as VideocamIcon,
  CheckCircle as CheckCircleIcon,
} from '@mui/icons-material';
import { useWebSocket } from '../../hooks/useWebSocket';
import { Metrics } from '../../types';
import MetricCard from './MetricCard';
import AlertChart from './AlertChart';

const Dashboard: React.FC = () => {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [loading, setLoading] = useState(true);

  const { lastMessage, isConnected } = useWebSocket(
    'ws://localhost:8000/ws/dashboard',
    {
      onMessage: (message) => {
        if (message.type === 'metrics_update') {
          setMetrics(message.data);
          setLoading(false);
        }
      },
    }
  );

  // 初始加载数据
  useEffect(() => {
    fetch('/api/v1/helmet/platform/overview')
      .then((res) => res.json())
      .then((data) => {
        setMetrics(data.metrics);
        setLoading(false);
      })
      .catch((error) => {
        console.error('Failed to load metrics:', error);
        setLoading(false);
      });
  }, []);

  if (loading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight="400px">
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box sx={{ p: 3 }}>
      {/* 连接状态指示器 */}
      <Box sx={{ mb: 2, display: 'flex', alignItems: 'center', gap: 1 }}>
        <Box
          sx={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            bgcolor: isConnected ? 'success.main' : 'error.main',
          }}
        />
        <Typography variant="caption" color="text.secondary">
          {isConnected ? '实时连接' : '连接断开'}
        </Typography>
      </Box>

      {/* 指标卡片 */}
      <Grid container spacing={3}>
        <Grid item xs={12} sm={6} md={3}>
          <MetricCard
            title="总告警"
            value={metrics?.total_alerts || 0}
            icon={<WarningIcon />}
            color="error"
            trend="+12%"
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <MetricCard
            title="活跃摄像头"
            value={metrics?.active_cameras || 0}
            icon={<VideocamIcon />}
            color="primary"
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <MetricCard
            title="待处理"
            value={metrics?.pending_alerts || 0}
            icon={<TrendingUpIcon />}
            color="warning"
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <MetricCard
            title="已解决"
            value={metrics?.resolved_alerts || 0}
            icon={<CheckCircleIcon />}
            color="success"
          />
        </Grid>
      </Grid>

      {/* 图表区域 */}
      <Grid container spacing={3} sx={{ mt: 2 }}>
        <Grid item xs={12} md={8}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                告警趋势
              </Typography>
              <AlertChart data={metrics?.alerts_by_department || {}} />
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={4}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                按部门分布
              </Typography>
              {/* 部门分布图表 */}
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </Box>
  );
};

export default Dashboard;
