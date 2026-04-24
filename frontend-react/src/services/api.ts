import axios from 'axios';
import { Alert, Camera, SystemStats, ApiResponse, PaginatedResponse } from '../types';

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// 请求拦截器
api.interceptors.request.use(
  (config) => {
    // 可以在这里添加认证token
    // const token = localStorage.getItem('token');
    // if (token) {
    //   config.headers.Authorization = `Bearer ${token}`;
    // }
    return config;
  },
  (error) => Promise.reject(error)
);

// 响应拦截器
api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    console.error('API Error:', error);
    return Promise.reject(error);
  }
);

// API方法
export const alertsApi = {
  getAll: (params?: { page?: number; page_size?: number; severity?: string }) =>
    api.get<any, PaginatedResponse<Alert>>('/api/v1/helmet/alerts', { params }),

  getById: (id: string) =>
    api.get<any, ApiResponse<Alert>>(`/api/v1/helmet/alerts/${id}`),

  acknowledge: (id: string) =>
    api.post<any, ApiResponse<void>>(`/api/v1/helmet/alerts/${id}/status`, { status: 'acknowledged' }),

  getRecent: async (limit: number = 50): Promise<ApiResponse<Alert[]>> => {
    try {
      const response = await api.get<any, any>('/api/v1/helmet/platform/overview');
      const alerts = response.recent_alerts || [];

      // 转换为前端期望的格式
      const formattedAlerts: Alert[] = alerts.slice(0, limit).map((alert: any) => ({
        id: alert.alert_id || alert.id,
        camera_id: alert.camera_id,
        camera_name: alert.camera_name || 'Unknown Camera',
        timestamp: alert.created_at || alert.timestamp,
        severity: alert.severity || 'medium',
        violation_type: alert.violation_type || 'No Helmet',
        image_url: alert.snapshot_url,
        acknowledged: alert.status === 'acknowledged',
      }));

      return {
        success: true,
        data: formattedAlerts,
      };
    } catch (error) {
      console.error('Failed to fetch alerts:', error);
      return {
        success: false,
        error: 'Failed to fetch alerts',
        data: [],
      };
    }
  },
};

export const camerasApi = {
  getAll: () =>
    api.get<any, ApiResponse<Camera[]>>('/api/v1/helmet/cameras'),

  getById: (id: string) =>
    api.get<any, ApiResponse<Camera>>(`/api/v1/helmet/cameras/${id}`),

  updateStatus: (id: string, status: string) =>
    api.patch<any, ApiResponse<void>>(`/api/v1/helmet/cameras/${id}/status`, { status }),
};

export const metricsApi = {
  getSystemStats: async (): Promise<ApiResponse<SystemStats>> => {
    try {
      const response = await api.get<any, any>('/api/v1/helmet/platform/overview');

      // 转换后端数据为前端期望的格式
      const stats: SystemStats = {
        total_cameras: response.cameras?.length || 0,
        active_cameras: response.cameras?.filter((c: any) => c.status === 'online').length || 0,
        total_alerts: response.stats?.total_alerts || 0,
        critical_alerts: response.stats?.critical_alerts || 0,
        detection_rate: response.stats?.detection_rate || 0,
        system_uptime: response.stats?.system_uptime || 0,
        cpu_usage: response.stats?.cpu_usage || 0,
        memory_usage: response.stats?.memory_usage || 0,
      };

      return {
        success: true,
        data: stats,
      };
    } catch (error) {
      console.error('Failed to fetch system stats:', error);
      return {
        success: false,
        error: 'Failed to fetch system stats',
      };
    }
  },

  getTimeSeries: (metric: string, timeRange: string) =>
    api.get<any, ApiResponse<any>>('/api/v1/helmet/reports/summary', {
      params: { metric, time_range: timeRange },
    }),
};

export default api;
