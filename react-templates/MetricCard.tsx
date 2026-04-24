// src/components/Dashboard/MetricCard.tsx
// 指标卡片组件

import React from 'react';
import {
  Card,
  CardContent,
  Typography,
  Box,
  Avatar,
} from '@mui/material';
import { TrendingUp as TrendingUpIcon } from '@mui/icons-material';

interface MetricCardProps {
  title: string;
  value: number | string;
  icon: React.ReactNode;
  color: 'primary' | 'secondary' | 'error' | 'warning' | 'info' | 'success';
  trend?: string;
}

const MetricCard: React.FC<MetricCardProps> = ({
  title,
  value,
  icon,
  color,
  trend,
}) => {
  return (
    <Card
      sx={{
        height: '100%',
        transition: 'transform 0.2s, box-shadow 0.2s',
        '&:hover': {
          transform: 'translateY(-4px)',
          boxShadow: 4,
        },
      }}
    >
      <CardContent>
        <Box display="flex" justifyContent="space-between" alignItems="flex-start">
          <Box>
            <Typography color="text.secondary" variant="body2" gutterBottom>
              {title}
            </Typography>
            <Typography variant="h4" component="div" sx={{ fontWeight: 600 }}>
              {value}
            </Typography>
            {trend && (
              <Box display="flex" alignItems="center" mt={1}>
                <TrendingUpIcon fontSize="small" color="success" />
                <Typography variant="caption" color="success.main" sx={{ ml: 0.5 }}>
                  {trend}
                </Typography>
              </Box>
            )}
          </Box>
          <Avatar
            sx={{
              bgcolor: `${color}.main`,
              width: 56,
              height: 56,
            }}
          >
            {icon}
          </Avatar>
        </Box>
      </CardContent>
    </Card>
  );
};

export default MetricCard;
