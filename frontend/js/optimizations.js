/**
 * Frontend Optimization Integration
 *
 * Integrates performance optimizations into existing pages:
 * - Skeleton screens
 * - Optimistic updates
 * - Adaptive polling
 * - Virtual scrolling
 */

import { skeleton, optimistic, AdaptivePoller, VisibilityAwarePoller, requestDeduplicator } from './performance.js';
import { VirtualTable, LazyImageLoader } from './virtual-scroll.js';
import { api } from './api.js';
import { toast } from './components/toast.js';

// ============================================================================
// Review Page Optimizations
// ============================================================================

/**
 * Enhanced alert detail loading with skeleton screen
 */
export async function fetchAlertDetailOptimized(container, alertId) {
  // Show skeleton immediately
  const detailPane = container.querySelector('.review-detail-pane');
  if (detailPane) {
    detailPane.innerHTML = skeleton.alertDetail();
  }

  try {
    // Deduplicate concurrent requests
    const detail = await requestDeduplicator.execute(
      `alert-detail-${alertId}`,
      () => api.alerts.get(alertId)
    );

    return detail;
  } catch (error) {
    console.error('Failed to fetch alert detail:', error);
    throw error;
  }
}

/**
 * Optimistic alert status update
 */
export async function updateAlertStatusOptimistic(alertId, newStatus, updateUI, rollbackUI) {
  const key = `alert-status-${alertId}`;

  try {
    await optimistic.apply(
      key,
      // Apply optimistic update
      () => updateUI(alertId, newStatus),
      // Rollback on failure
      () => {
        rollbackUI(alertId);
        toast.error('更新失败', '状态更新失败，已回滚');
      },
      // Actual API call
      api.alerts.updateStatus(alertId, { status: newStatus })
    );

    toast.success('更新成功', `状态已更新为: ${newStatus}`);
  } catch (error) {
    // Error already handled by optimistic manager
    console.error('Status update failed:', error);
  }
}

/**
 * Optimistic alert assignment
 */
export async function assignAlertOptimistic(alertId, assignedTo, updateUI, rollbackUI) {
  const key = `alert-assign-${alertId}`;

  try {
    await optimistic.apply(
      key,
      () => updateUI(alertId, assignedTo),
      () => {
        rollbackUI(alertId);
        toast.error('分配失败', '告警分配失败，已回滚');
      },
      api.alerts.assign(alertId, { assigned_to: assignedTo })
    );

    toast.success('分配成功', `已分配给: ${assignedTo}`);
  } catch (error) {
    console.error('Assignment failed:', error);
  }
}

// ============================================================================
// Dashboard Page Optimizations
// ============================================================================

/**
 * Adaptive polling for dashboard metrics
 */
export function createDashboardPoller(onUpdate) {
  const poller = new AdaptivePoller(
    // Fetch function
    async () => {
      const data = await api.dashboard.overview();
      return data;
    },
    {
      baseInterval: 10000, // 10 seconds
      maxInterval: 60000,  // 60 seconds
      backoffMultiplier: 1.5,
      onData: (data, hasChanged) => {
        onUpdate(data, hasChanged);

        if (hasChanged) {
          console.log('[Dashboard] Data changed, polling at base interval');
        }
      },
      onError: (error) => {
        console.error('[Dashboard] Polling error:', error);
      }
    }
  );

  // Make it visibility-aware
  return new VisibilityAwarePoller(poller);
}

/**
 * Load dashboard with skeleton
 */
export async function loadDashboardOptimized(container) {
  // Show skeleton cards
  const metricsContainer = container.querySelector('.metrics-grid');
  if (metricsContainer) {
    metricsContainer.innerHTML = Array(6).fill(0)
      .map(() => skeleton.dashboardCard())
      .join('');
  }

  try {
    const data = await api.dashboard.overview();
    return data;
  } catch (error) {
    console.error('Failed to load dashboard:', error);
    throw error;
  }
}

// ============================================================================
// Reports Page Optimizations
// ============================================================================

/**
 * Virtual scrolling for large alert tables
 */
export function createVirtualAlertTable(container, alerts, onRowClick) {
  return new VirtualTable(container, {
    data: alerts,
    rowHeight: 60,
    overscan: 5,
    renderRow: (alert, index) => {
      return `
        <div class="alert-row" style="display: flex; align-items: center; padding: 12px; border-bottom: 1px solid rgba(0,255,136,0.1);">
          <div class="alert-id" style="flex: 0 0 120px;">${alert.alert_id || '--'}</div>
          <div class="alert-camera" style="flex: 1;">${alert.camera_name || '--'}</div>
          <div class="alert-status" style="flex: 0 0 100px;">
            <span class="status-badge status-${alert.status}">${alert.status}</span>
          </div>
          <div class="alert-time" style="flex: 0 0 150px;">${new Date(alert.created_at).toLocaleString()}</div>
        </div>
      `;
    },
    onRowClick: onRowClick
  });
}

/**
 * Lazy load alert images
 */
export function enableLazyImageLoading(container) {
  const lazyLoader = new LazyImageLoader({
    rootMargin: '100px',
    threshold: 0.01
  });

  lazyLoader.observe(container);

  return lazyLoader;
}

// ============================================================================
// Camera Page Optimizations
// ============================================================================

/**
 * Adaptive polling for camera live frames
 */
export function createCameraFramePoller(cameraId, onUpdate) {
  const poller = new AdaptivePoller(
    async () => {
      const frame = await api.cameras.getLiveFrame(cameraId);
      return frame;
    },
    {
      baseInterval: 5000,  // 5 seconds
      maxInterval: 30000,  // 30 seconds
      backoffMultiplier: 1.3,
      onData: (frame, hasChanged) => {
        onUpdate(frame, hasChanged);
      },
      onError: (error) => {
        console.error(`[Camera ${cameraId}] Frame polling error:`, error);
      }
    }
  );

  return new VisibilityAwarePoller(poller);
}

/**
 * Batch load multiple camera frames
 */
export async function loadCameraFramesBatch(cameraIds) {
  // Load all frames in parallel
  const promises = cameraIds.map(id =>
    requestDeduplicator.execute(
      `camera-frame-${id}`,
      () => api.cameras.getLiveFrame(id)
    )
  );

  try {
    const frames = await Promise.allSettled(promises);

    return frames.map((result, index) => ({
      cameraId: cameraIds[index],
      frame: result.status === 'fulfilled' ? result.value : null,
      error: result.status === 'rejected' ? result.reason : null
    }));
  } catch (error) {
    console.error('Batch frame loading failed:', error);
    return [];
  }
}

// ============================================================================
// Global Optimizations
// ============================================================================

/**
 * Preload critical resources
 */
export function preloadCriticalResources() {
  // Preload API endpoints that are likely to be needed
  const criticalEndpoints = [
    () => api.dashboard.overview(),
    () => api.cameras.list(),
    () => api.alerts.list({ limit: 10 })
  ];

  // Fire and forget - results will be cached
  criticalEndpoints.forEach(fn => {
    fn().catch(err => console.warn('Preload failed:', err));
  });
}

/**
 * Setup global performance monitoring
 */
export function setupPerformanceMonitoring() {
  // Monitor long tasks
  if ('PerformanceObserver' in window) {
    try {
      const observer = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          if (entry.duration > 50) {
            console.warn('[Performance] Long task detected:', {
              duration: entry.duration,
              startTime: entry.startTime
            });
          }
        }
      });

      observer.observe({ entryTypes: ['longtask'] });
    } catch (e) {
      // longtask not supported
    }
  }

  // Monitor navigation timing
  window.addEventListener('load', () => {
    setTimeout(() => {
      const perfData = performance.getEntriesByType('navigation')[0];
      if (perfData) {
        console.log('[Performance] Page load metrics:', {
          domContentLoaded: perfData.domContentLoadedEventEnd - perfData.domContentLoadedEventStart,
          loadComplete: perfData.loadEventEnd - perfData.loadEventStart,
          domInteractive: perfData.domInteractive - perfData.fetchStart,
          totalTime: perfData.loadEventEnd - perfData.fetchStart
        });
      }
    }, 0);
  });
}

/**
 * Cleanup on page unload
 */
export function setupCleanup() {
  window.addEventListener('beforeunload', () => {
    // Rollback any pending optimistic updates
    optimistic.rollbackAll();

    // Clear request cache
    requestDeduplicator.clear();
  });
}

// ============================================================================
// Initialize all optimizations
// ============================================================================

export function initializeOptimizations() {
  console.log('[Optimizations] Initializing frontend performance optimizations...');

  // Setup global monitoring
  setupPerformanceMonitoring();

  // Setup cleanup handlers
  setupCleanup();

  // Preload critical resources
  preloadCriticalResources();

  console.log('[Optimizations] Frontend optimizations initialized');
}

// Auto-initialize when module loads
if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeOptimizations);
  } else {
    initializeOptimizations();
  }
}
