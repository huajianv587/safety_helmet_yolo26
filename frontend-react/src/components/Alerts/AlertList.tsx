import React, { useMemo } from 'react';
import { List, RowComponentProps } from 'react-window';
import {
  Box,
  Paper,
  Typography,
  Chip,
  Avatar,
  ListItem,
  ListItemAvatar,
  ListItemText,
  Divider,
} from '@mui/material';
import WarningIcon from '@mui/icons-material/Warning';
import ErrorIcon from '@mui/icons-material/Error';
import InfoIcon from '@mui/icons-material/Info';
import { Alert } from '../../types';
import { formatDistanceToNow } from 'date-fns';

interface AlertListProps {
  alerts: Alert[];
  maxItems?: number;
  onAlertClick?: (alert: Alert) => void;
}

interface AlertRowProps {
  alerts: Alert[];
  onAlertClick?: (alert: Alert) => void;
}

const AlertList: React.FC<AlertListProps> = ({ alerts, maxItems = 100, onAlertClick }) => {
  const displayAlerts = useMemo(() => alerts.slice(0, maxItems), [alerts, maxItems]);

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'critical':
        return 'error';
      case 'high':
        return 'warning';
      case 'medium':
        return 'info';
      default:
        return 'default';
    }
  };

  const getSeverityIcon = (severity: string) => {
    switch (severity) {
      case 'critical':
        return <ErrorIcon />;
      case 'high':
        return <WarningIcon />;
      default:
        return <InfoIcon />;
    }
  };

  const Row = ({ index, style, alerts: rowAlerts, onAlertClick: handleAlertClick, ariaAttributes }: RowComponentProps<AlertRowProps>) => {
    const alert = rowAlerts[index];

    return (
      <div style={style} {...ariaAttributes}>
        <ListItem
          onClick={() => handleAlertClick?.(alert)}
          sx={{
            cursor: 'pointer',
            '&:hover': {
              backgroundColor: 'action.hover',
            },
          }}
        >
          <ListItemAvatar>
            <Avatar sx={{ bgcolor: `${getSeverityColor(alert.severity)}.main` }}>
              {getSeverityIcon(alert.severity)}
            </Avatar>
          </ListItemAvatar>
          <ListItemText
            primary={
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <Typography variant="body1" sx={{ fontWeight: 500 }}>
                  {alert.camera_name}
                </Typography>
                <Chip
                  label={alert.severity}
                  size="small"
                  color={getSeverityColor(alert.severity) as any}
                />
              </Box>
            }
            secondary={
              <Box>
                <Typography variant="body2" color="text.secondary">
                  {alert.violation_type}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {formatDistanceToNow(new Date(alert.timestamp), { addSuffix: true })}
                </Typography>
              </Box>
            }
          />
        </ListItem>
        {index < rowAlerts.length - 1 && <Divider />}
      </div>
    );
  };

  if (displayAlerts.length === 0) {
    return (
      <Paper sx={{ p: 3, textAlign: 'center' }}>
        <Typography variant="body1" color="text.secondary">
          No alerts to display
        </Typography>
      </Paper>
    );
  }

  return (
    <Paper sx={{ height: '100%', overflow: 'hidden' }}>
      <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider' }}>
        <Typography variant="h6">Recent Alerts</Typography>
        <Typography variant="body2" color="text.secondary">
          {displayAlerts.length} alerts
        </Typography>
      </Box>
      <List
        rowComponent={Row}
        rowCount={displayAlerts.length}
        rowHeight={100}
        rowProps={{
          alerts: displayAlerts,
          onAlertClick,
        }}
        style={{ height: 600, width: '100%' }}
      >
      </List>
    </Paper>
  );
};

export default AlertList;
