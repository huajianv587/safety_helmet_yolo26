// src/types/index.ts
// TypeScript类型定义

export interface Alert {
  alert_id: string;
  event_no: string;
  camera_id: string;
  camera_name: string;
  person_id?: string;
  person_name?: string;
  employee_id?: string;
  department: string;
  status: 'pending' | 'confirmed' | 'resolved' | 'false_positive';
  risk_level: 'low' | 'medium' | 'high';
  created_at: string;
  updated_at: string;
  snapshot_display_url?: string;
}

export interface Camera {
  camera_id: string;
  camera_name: string;
  source: string;
  enabled: boolean;
  location: string;
  department: string;
  last_status: 'online' | 'offline' | 'error';
  last_seen_at?: string;
  last_fps?: number;
}

export interface Metrics {
  total_alerts: number;
  active_cameras: number;
  pending_alerts: number;
  resolved_alerts: number;
  alerts_by_department: Record<string, number>;
  alerts_by_status: Record<string, number>;
}

export interface WebSocketMessage {
  type: string;
  topic: string;
  sequence: number;
  sent_at: string;
  data: any;
}

export interface CacheStats {
  hits: number;
  misses: number;
  hit_rate_percent: number;
  total_entries: number;
}

export interface TaskQueueStats {
  queue_size: number;
  total_tasks: number;
  pending: number;
  running: number;
  completed: number;
  failed: number;
  workers: number;
}
