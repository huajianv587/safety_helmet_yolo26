// src/components/Alerts/AlertList.tsx
// 告警列表组件（带虚拟滚动）

import React from 'react';
import { FixedSizeList } from 'react-window';
import {
  Card,
  CardContent,
  Typography,
  Chip,
  Box,
  Avatar,
} from '@mui/material';
import {
  Warning as WarningIcon,
  CheckCircle as CheckCircleIcon,
  Error as ErrorIcon,
} from '@mui/icons-material';
import { Alert } from '../../types';

interface AlertListProps {
  alerts: Alert[];
  onAlertClick?: (alert: Alert) => void;
}

const getStatusColor = (status: string) => {
  switch (status) {
    case 'pending':
      return 'warning';
    case 'confirmed':
      return 'error';
    case 'resolved':
      return 'success';
    case 'false_positive':
      return 'default';
    default:
      return 'default';
  }
};

const getStatusIcon = (status: string) => {
  switch (status) {
    case 'pending':
      return <WarningIcon fontSize="small" />;
    case 'confirmed':
      return <ErrorIcon fontSize="small" />;
    case 'resolved':
      return <CheckCircleIcon fontSize="small" />;
    default:
      return <WarningIcon fontSize="small" />;
  }
};

const AlertList: React.FC<AlertListProps> = ({ alerts, onAlertClick }) => {
  const Row = ({ index, style }: { index: number; style: React.CSSProperties }) => {
    const alert = alerts[index];

    return (
      <div style={style}>
        <Card
          sx={{
            m: 1,
            cursor: 'pointer',
            transition: 'all 0.2s',
            '&:hover': {
              boxShadow: 3,
              transform: 'translateX(4px)',
            },
          }}
          onClick={() => onAlertClick?.(alert)}
        >
          <CardContent>
            <Box display="flex" alignItems="center" gap={2}>
              <Avatar
                sx={{
                  bgcolor: `${getStatusColor(alert.status)}.light`,
                  color: `${getStatusColor(alert.status)}.dark`,
                }}
              >
                {getStatusIcon(alert.status)}
              </Avatar>
              <Box flex={1}>
                <Typography variant="h6" component="div">
                  {alert.camera_name}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {alert.department} • {new Date(alert.created_at).toLocaleString()}
                </Typography>
                {alert.person_name && (
                  <Typography variant="body2" color="text.secondary">
                    人员: {alert.person_name}
                  </Typography>
                )}
              </Box>
              <Box>
                <Chip
                  label={alert.status}
                  color={getStatusColor(alert.status) as any}
                  size="small"
                  sx={{ mb: 1 }}
                />
                <Chip
                  label={alert.risk_level}
                  color={alert.risk_level === 'high' ? 'error' : 'default'}
                  size="small"
                  variant="outlined"
                />
              </Box>
            </Box>
          </CardContent>
        </Card>
      </div>
    );
  };

  return (
    <FixedSizeList
      height={600}
      itemCount={alerts.length}
      itemSize={140}
      width="100%"
    >
      {Row}
    </FixedSizeList>
  );
};

export default AlertList;
