import React from 'react';
import { Card, CardContent, Typography, Box, CircularProgress } from '@mui/material';
import TrendingUpIcon from '@mui/icons-material/TrendingUp';
import TrendingDownIcon from '@mui/icons-material/TrendingDown';
import RemoveIcon from '@mui/icons-material/Remove';
import { Metric } from '../../types';

interface MetricCardProps {
  metric: Metric;
  loading?: boolean;
}

const MetricCard: React.FC<MetricCardProps> = ({ metric, loading = false }) => {
  const getTrendIcon = () => {
    switch (metric.trend) {
      case 'up':
        return <TrendingUpIcon sx={{ color: 'success.main' }} />;
      case 'down':
        return <TrendingDownIcon sx={{ color: 'error.main' }} />;
      default:
        return <RemoveIcon sx={{ color: 'text.secondary' }} />;
    }
  };

  const getTrendColor = () => {
    switch (metric.trend) {
      case 'up':
        return 'success.main';
      case 'down':
        return 'error.main';
      default:
        return 'text.secondary';
    }
  };

  if (loading) {
    return (
      <Card sx={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <CircularProgress />
      </Card>
    );
  }

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
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 2 }}>
          <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 500 }}>
            {metric.name}
          </Typography>
          {metric.trend && getTrendIcon()}
        </Box>

        <Typography variant="h4" component="div" sx={{ mb: 1, fontWeight: 600 }}>
          {metric.value.toLocaleString()}
          {metric.unit && (
            <Typography component="span" variant="h6" color="text.secondary" sx={{ ml: 0.5 }}>
              {metric.unit}
            </Typography>
          )}
        </Typography>

        {metric.change !== undefined && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <Typography variant="body2" sx={{ color: getTrendColor(), fontWeight: 500 }}>
              {metric.change > 0 ? '+' : ''}{metric.change}%
            </Typography>
            <Typography variant="body2" color="text.secondary">
              vs last period
            </Typography>
          </Box>
        )}
      </CardContent>
    </Card>
  );
};

export default MetricCard;
