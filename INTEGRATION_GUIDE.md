# 优化模块集成指南

本文档提供将所有优化模块集成到现有系统的详细步骤。

---

## 快速开始

### 1. 安装依赖

```bash
# 添加到requirements.txt
prometheus-client==0.20.0
websockets==12.0

# 安装
pip install -r requirements.txt
```

### 2. 修改app.py

在 `src/helmet_monitoring/api/app.py` 中进行以下修改：

```python
# ============================================================================
# 1. 导入优化模块
# ============================================================================

from helmet_monitoring.storage.indexed_repository import IndexedLocalAlertRepository
from helmet_monitoring.services.optimized_dashboard import OptimizedDashboardAggregator
from helmet_monitoring.api.cache_manager import get_cache_manager, CacheTier
from helmet_monitoring.api.cache_integration import warm_cache_on_startup, invalidate_alert_caches
from helmet_monitoring.tasks import init_task_system, shutdown_task_system
from helmet_monitoring.tasks.notification_tasks import send_alert_notification
from helmet_monitoring.api.websocket import (
    get_connection_manager,
    websocket_alerts_handler,
    websocket_dashboard_handler,
    broadcast_alert_created,
    broadcast_alert_updated
)
from helmet_monitoring.monitoring.prometheus import (
    get_metrics,
    track_api_request,
    update_cache_metrics,
    update_alert_metrics,
    update_task_queue_metrics,
    update_websocket_metrics
)

# ============================================================================
# 2. 替换Repository为索引版本
# ============================================================================

def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="Safety Helmet Monitoring API")
    
    # 使用索引Repository替代标准Repository
    repository = IndexedLocalAlertRepository(settings.data_dir)
    
    # 创建优化的Dashboard聚合器
    dashboard_aggregator = OptimizedDashboardAggregator(settings)
    
    # ... 其他初始化代码

# ============================================================================
# 3. 添加启动事件
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """应用启动时执行"""
    print("[Startup] Initializing optimizations...")
    
    # 启动任务系统
    init_task_system()
    
    # 预热缓存
    warm_cache_on_startup(repository, dashboard_aggregator)
    
    print("[Startup] All optimizations initialized")

@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭时执行"""
    print("[Shutdown] Cleaning up...")
    shutdown_task_system()
    print("[Shutdown] Complete")

# ============================================================================
# 4. 修改API端点使用缓存
# ============================================================================

@app.get("/api/v1/alerts")
@track_api_request("/api/v1/alerts")
def list_alerts(
    limit: int = 100,
    camera_id: Optional[str] = None,
    status: Optional[str] = None,
    since: Optional[str] = None
):
    """列出告警（带缓存）"""
    cache = get_cache_manager()
    
    # 构建缓存键
    cache_key = ("alerts", "list", f"limit={limit},camera={camera_id},status={status},since={since}")
    
    # 尝试从缓存获取
    cached = cache.get(cache_key, CacheTier.SUMMARIES)
    if cached:
        return cached
    
    # 缓存未命中，查询数据库
    alerts = repository.list_alerts(
        limit=limit,
        camera_id=camera_id,
        status=status,
        since=since
    )
    
    # 存入缓存（30秒TTL）
    cache.set(cache_key, alerts, CacheTier.SUMMARIES)
    
    return alerts


@app.get("/api/v1/platform-overview")
@track_api_request("/api/v1/platform-overview")
def platform_overview(days: int = 7):
    """平台概览（使用优化聚合）"""
    cache = get_cache_manager()
    
    cache_key = ("overview", f"days={days}")
    cached = cache.get(cache_key, CacheTier.SUMMARIES)
    if cached:
        return cached
    
    # 使用优化的聚合器
    overview = dashboard_aggregator.build_overview_payload(days=days)
    
    cache.set(cache_key, overview, CacheTier.SUMMARIES)
    return overview


@app.post("/api/v1/alerts/{alert_id}/status")
@track_api_request("/api/v1/alerts/status")
async def update_alert_status(alert_id: str, status: str):
    """更新告警状态（带缓存失效和WebSocket推送）"""
    # 更新数据库
    alert = repository.update_alert_status(alert_id, status)
    
    # 失效相关缓存
    invalidate_alert_caches(alert_id)
    
    # WebSocket实时推送
    await broadcast_alert_updated(alert_id, {"status": status})
    
    return alert


@app.post("/api/v1/alerts")
@track_api_request("/api/v1/alerts")
async def create_alert(alert_data: dict):
    """创建告警（异步通知）"""
    from helmet_monitoring.tasks.notification_tasks import send_alert_notification
    
    # 创建告警
    alert = repository.create_alert(alert_data)
    
    # 异步发送通知（不阻塞响应）
    task_id = send_alert_notification.delay(
        alert_id=alert['alert_id'],
        alert_type=alert['type'],
        camera_name=alert['camera_name'],
        timestamp=alert['timestamp'],
        image_url=alert.get('image_url')
    )
    
    # WebSocket实时推送
    await broadcast_alert_created(alert)
    
    return {"alert": alert, "notification_task": task_id}

# ============================================================================
# 5. 添加WebSocket端点
# ============================================================================

@app.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    """告警实时推送"""
    await websocket_alerts_handler(websocket)


@app.websocket("/ws/dashboard")
async def websocket_dashboard(websocket: WebSocket):
    """仪表板实时更新"""
    await websocket_dashboard_handler(websocket)

# ============================================================================
# 6. 添加监控端点
# ============================================================================

@app.get("/metrics")
def metrics():
    """Prometheus指标"""
    data, content_type = get_metrics()
    return Response(content=data, media_type=content_type)


@app.get("/ops/cache/stats")
def cache_stats():
    """缓存统计"""
    cache = get_cache_manager()
    stats = cache.get_stats()
    
    # 更新Prometheus指标
    update_cache_metrics(stats)
    
    return stats


@app.get("/ops/tasks/stats")
def task_stats():
    """任务队列统计"""
    from helmet_monitoring.tasks import get_queue_stats
    
    stats = get_queue_stats()
    update_task_queue_metrics(stats)
    
    return stats


@app.get("/ops/websocket/stats")
def websocket_stats():
    """WebSocket连接统计"""
    manager = get_connection_manager()
    stats = manager.get_stats()
    
    update_websocket_metrics(stats)
    
    return stats
```

---

## 前端集成

### 1. 引入优化模块

在 `frontend/index.html` 中添加：

```html
<!-- 在</body>前添加 -->
<script type="module" src="/js/performance.js"></script>
<script type="module" src="/js/virtual-scroll.js"></script>
<script type="module" src="/js/optimizations.js"></script>
```

### 2. 修改review.js

```javascript
// 在review.js顶部导入
import { initReviewPageOptimizations } from './optimizations.js';

// 在页面初始化时调用
document.addEventListener('DOMContentLoaded', () => {
    // 启用所有优化
    initReviewPageOptimizations();
    
    // 原有初始化代码...
});
```

### 3. WebSocket集成示例

```javascript
// 在review.js中添加WebSocket连接
let alertsWebSocket = null;

function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/alerts`;
    
    alertsWebSocket = new WebSocket(wsUrl);
    
    alertsWebSocket.onopen = () => {
        console.log('[WebSocket] Connected to alerts stream');
    };
    
    alertsWebSocket.onmessage = (event) => {
        const message = JSON.parse(event.data);
        
        switch (message.type) {
            case 'alert_created':
                // 实时添加新告警到列表顶部
                prependAlertToQueue(message.data);
                showNotification('新告警', message.data.camera_name);
                break;
                
            case 'alert_updated':
                // 实时更新告警状态
                updateAlertInQueue(message.alert_id, message.updates);
                break;
        }
    };
    
    alertsWebSocket.onerror = (error) => {
        console.error('[WebSocket] Error:', error);
    };
    
    alertsWebSocket.onclose = () => {
        console.log('[WebSocket] Disconnected, reconnecting in 5s...');
        setTimeout(connectWebSocket, 5000);
    };
}

// 页面加载时连接
connectWebSocket();
```

---

## 渐进式集成策略

如果不想一次性集成所有优化，可以按以下顺序逐步启用：

### 阶段1: 缓存系统（最小风险，最大收益）

```python
# 只启用缓存，不修改其他代码
from helmet_monitoring.api.cache_manager import get_cache_manager, CacheTier

@app.get("/api/v1/alerts")
def list_alerts(...):
    cache = get_cache_manager()
    cache_key = ("alerts", "list", ...)
    
    cached = cache.get(cache_key, CacheTier.SUMMARIES)
    if cached:
        return cached
    
    # 原有查询逻辑
    alerts = repository.list_alerts(...)
    cache.set(cache_key, alerts, CacheTier.SUMMARIES)
    return alerts
```

**预期收益**: 30-50%性能提升

### 阶段2: 索引Repository（需要测试）

```python
# 替换Repository实现
from helmet_monitoring.storage.indexed_repository import IndexedLocalAlertRepository

repository = IndexedLocalAlertRepository(settings.data_dir)
```

**预期收益**: 额外40-60%查询性能提升

### 阶段3: 前端优化（独立模块）

```javascript
// 启用骨架屏和乐观更新
import { SkeletonLoader, OptimisticUpdater } from './performance.js';

const skeleton = new SkeletonLoader();
const optimistic = new OptimisticUpdater();
```

**预期收益**: 用户感知性能提升50-70%

### 阶段4: 异步任务（可选）

```python
# 异步化耗时操作
from helmet_monitoring.tasks.notification_tasks import send_alert_notification

task_id = send_alert_notification.delay(...)
```

**预期收益**: API响应时间减少60-80%

### 阶段5: WebSocket（可选）

```python
# 添加实时推送
await broadcast_alert_created(alert)
```

**预期收益**: 实时性提升90%+

---

## 验证清单

集成完成后，使用以下清单验证：

### 功能验证

- [ ] 告警列表正常加载
- [ ] 告警详情正常显示
- [ ] 状态更新正常工作
- [ ] 仪表板数据正确
- [ ] 缓存命中率>50%
- [ ] 任务队列正常运行
- [ ] WebSocket连接成功
- [ ] Prometheus指标可访问

### 性能验证

```bash
# 运行性能测试
cd tests/performance
python benchmark.py

# 检查结果
cat performance_benchmark_report.md
```

预期结果：
- 告警列表查询: <100ms
- 仪表板加载: <200ms
- 缓存命中率: >70%

### 监控验证

1. 访问 `http://localhost:8000/metrics` 查看Prometheus指标
2. 访问 `http://localhost:8000/ops/cache/stats` 查看缓存统计
3. 访问 `http://localhost:8000/ops/tasks/stats` 查看任务队列状态

---

## 故障排查

### 问题1: 缓存未命中率高

**原因**: 缓存键不一致或TTL过短

**解决**:
```python
# 检查缓存统计
stats = cache.get_stats()
print(f"Hit rate: {stats['hit_rate']}")

# 调整TTL
cache.set(key, value, CacheTier.STATIC)  # 使用更长的TTL
```

### 问题2: 索引Repository内存占用高

**原因**: 数据量过大

**解决**:
```python
# 限制索引大小
class IndexedLocalAlertRepository:
    MAX_CACHE_SIZE = 5000  # 只缓存最近5000条
```

### 问题3: WebSocket连接失败

**原因**: 防火墙或代理问题

**解决**:
```javascript
// 添加重连逻辑
alertsWebSocket.onclose = () => {
    setTimeout(connectWebSocket, 5000);
};
```

### 问题4: 任务队列堆积

**原因**: 工作线程不足

**解决**:
```python
# 增加工作线程
queue = SimpleTaskQueue(num_workers=4)  # 默认2
```

---

## 回滚方案

如果遇到问题需要回滚：

### 1. 禁用缓存

```python
# 注释掉缓存相关代码
# cached = cache.get(...)
# if cached:
#     return cached

# 直接查询
return repository.list_alerts(...)
```

### 2. 恢复标准Repository

```python
from helmet_monitoring.storage.local_alert_repository import LocalAlertRepository

repository = LocalAlertRepository(settings.data_dir)
```

### 3. 禁用WebSocket

```python
# 注释掉WebSocket端点
# @app.websocket("/ws/alerts")
# async def websocket_alerts(websocket: WebSocket):
#     ...
```

### 4. 禁用异步任务

```python
# 同步发送通知
send_email_notification(...)  # 不使用.delay()
```

---

## 生产环境建议

### 1. 监控告警

配置Prometheus告警规则：

```yaml
# prometheus-alerts.yml
groups:
  - name: helmet_monitoring
    rules:
      - alert: HighAPILatency
        expr: histogram_quantile(0.95, rate(api_request_duration_seconds_bucket[5m])) > 1
        for: 5m
        annotations:
          summary: "API响应时间过高"
      
      - alert: LowCacheHitRate
        expr: cache_hit_rate < 0.5
        for: 10m
        annotations:
          summary: "缓存命中率过低"
```

### 2. 日志配置

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
```

### 3. 资源限制

```python
# 限制缓存大小
cache = CacheManager(max_entries=10000)

# 限制任务队列
queue = SimpleTaskQueue(num_workers=4)

# 限制WebSocket连接
MAX_WEBSOCKET_CONNECTIONS = 1000
```

---

## 支持与反馈

如有问题，请查看：
- 优化报告: `OPTIMIZATION_REPORT.md`
- 路线图: `OPTIMIZATION_ROADMAP.md`
- 性能测试: `tests/performance/benchmark.py`

---

**文档版本**: 1.0  
**最后更新**: 2026-04-24
