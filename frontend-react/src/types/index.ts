// 核心数据类型定义
export interface Alert {
  id: string;
  camera_id: string;
  camera_name: string;
  timestamp: string;
  severity: 'critical' | 'high' | 'medium' | 'low';
  violation_type: string;
  image_url?: string;
  location?: string;
  worker_count?: number;
  acknowledged?: boolean;
}

export interface Camera {
  id: string;
  name: string;
  location: string;
  status: 'online' | 'offline' | 'error';
  stream_url: string;
  last_seen?: string;
  fps?: number;
  resolution?: string;
}

export interface Metric {
  name: string;
  value: number;
  unit: string;
  trend?: 'up' | 'down' | 'stable';
  change?: number;
  icon?: string;
  color?: string;
}

export interface SystemStats {
  total_cameras: number;
  active_cameras: number;
  total_alerts: number;
  critical_alerts: number;
  detection_rate: number;
  system_uptime: number;
  cpu_usage: number;
  memory_usage: number;
}

// WebSocket消息类型
export interface WSMessage {
  type: 'alert' | 'camera_status' | 'metrics' | 'system_status';
  data: any;
  timestamp: string;
}

// API响应类型
export interface ApiResponse<T> {
  success: boolean;
  data?: T;
  error?: string;
  message?: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  has_next: boolean;
  has_prev: boolean;
}

// 组件Props类型
export interface DashboardProps {
  refreshInterval?: number;
}

export interface AlertListProps {
  maxItems?: number;
  showFilters?: boolean;
}

export interface CameraGridProps {
  columns?: number;
  showOffline?: boolean;
}
