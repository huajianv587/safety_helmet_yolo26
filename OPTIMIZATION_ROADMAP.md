# Safety Helmet YOLO26 全面优化路线图

## 执行摘要

基于代码库深度分析，识别出7个关键性能瓶颈。本路线图提供分阶段优化方案，预计整体性能提升60-80%。

---

## 阶段1：数据库查询优化 (P0 - 关键路径)

**预计时间**: 3-4天  
**预计性能提升**: 70-80%（查询延迟）  
**风险等级**: 中等

### 1.1 消除LocalAlertRepository全表扫描

**问题**: 每次查询都读取整个JSONL文件到内存，然后Python循环过滤

**文件**: `src/helmet_monitoring/storage/repository.py` (行252-268)

**解决方案**:
```python
# 方案A: 添加内存索引（快速实现）
class LocalAlertRepository:
    def __init__(self):
        self._camera_index: dict[str, list[str]] = {}  # camera_id -> [alert_ids]
        self._date_index: dict[str, list[str]] = {}    # date -> [alert_ids]
        self._status_index: dict[str, list[str]] = {}  # status -> [alert_ids]
        self._rebuild_indexes()
    
    def _rebuild_indexes(self):
        """启动时构建索引，增量更新"""
        for alert in self._read_jsonl(self.alerts_file):
            self._add_to_indexes(alert)
    
    def list_alerts(self, *, camera_id=None, since=None, status=None, limit=100):
        # 使用索引快速定位候选集
        candidates = self._query_from_indexes(camera_id, since, status)
        return sorted(candidates, key=lambda x: x['created_at'], reverse=True)[:limit]

# 方案B: 迁移到SQLite（推荐长期方案）
# - 保持JSONL作为备份
# - SQLite提供索引和查询优化
# - 兼容现有API接口
```

**实施步骤**:
1. 实现内存索引系统（2天）
2. 添加索引更新钩子到insert/update方法
3. 性能基准测试（对比优化前后）
4. 可选：实现SQLite迁移路径

**验证指标**:
- 10K条数据查询时间: 从 ~500ms 降至 <50ms
- 内存占用: 增加 <10MB（索引开销）

---

### 1.2 优化仪表板聚合查询

**问题**: 单次overview请求触发3-4次数据库查询 + 多次内存遍历

**文件**: `src/helmet_monitoring/services/dashboard_api.py` (行293-354)

**解决方案**:
```python
# 方案A: 批量查询 + 单次遍历
def build_overview_payload_optimized(repository, days=7):
    since = datetime.now(tz=UTC) - timedelta(days=days)
    
    # 单次查询获取所有需要的数据
    alerts = repository.list_alerts(limit=1000, since=since)
    cameras = repository.list_cameras()
    visitor_records = repository.list_visitor_evidence(limit=100)
    
    # 单次遍历计算所有聚合
    metrics = {
        'total_alerts': 0,
        'by_department': defaultdict(int),
        'by_zone': defaultdict(int),
        'by_camera': defaultdict(int),
        'by_person': defaultdict(int),
    }
    
    for alert in alerts:
        metrics['total_alerts'] += 1
        metrics['by_department'][alert.get('department')] += 1
        metrics['by_zone'][alert.get('zone_name')] += 1
        # ... 一次遍历完成所有统计
    
    return {
        'metrics': metrics,
        'recent_alerts': alerts[:12],
        'cameras': cameras,
        # ...
    }

# 方案B: 预计算 + 增量更新（推荐）
class DashboardCache:
    """后台任务每分钟更新一次统计数据"""
    def __init__(self):
        self._metrics_cache = {}
        self._last_update = None
    
    def get_metrics(self, days=7):
        if self._is_stale():
            self._recompute()
        return self._metrics_cache
    
    def on_alert_created(self, alert):
        """增量更新统计"""
        self._metrics_cache['total_alerts'] += 1
        self._metrics_cache['by_department'][alert['department']] += 1
```

**实施步骤**:
1. 重构聚合逻辑为单次遍历（1天）
2. 实现DashboardCache类（1天）
3. 添加后台更新任务（使用APScheduler）
4. 集成到现有API端点

**验证指标**:
- Overview API响应时间: 从 ~800ms 降至 <100ms
- 数据库查询次数: 从 4次 降至 1次

---

## 阶段2：缓存策略增强 (P1 - 高ROI)

**预计时间**: 2-3天  
**预计性能提升**: 50-60%（高频端点）  
**风险等级**: 低

### 2.1 实现智能缓存预热

**当前问题**: 缓存冷启动导致首次请求慢

**解决方案**:
```python
# src/helmet_monitoring/api/cache_warmup.py
class CacheWarmer:
    def __init__(self, cache_manager, repository):
        self.cache = cache_manager
        self.repo = repository
    
    async def warmup_on_startup(self):
        """应用启动时预热关键缓存"""
        tasks = [
            self._warmup_overview(),
            self._warmup_cameras(),
            self._warmup_recent_alerts(),
        ]
        await asyncio.gather(*tasks)
    
    async def _warmup_overview(self):
        for days in [1, 7, 30]:  # 常用时间范围
            payload = build_overview_payload(self.repo, days=days)
            self.cache.set(f"overview:days={days}", payload, CacheTier.SUMMARIES)
    
    def schedule_periodic_refresh(self):
        """每5分钟刷新热点数据"""
        scheduler = BackgroundScheduler()
        scheduler.add_job(self._refresh_hot_caches, 'interval', minutes=5)
        scheduler.start()
```

**实施步骤**:
1. 创建CacheWarmer类（0.5天）
2. 集成到FastAPI startup事件
3. 添加后台刷新任务
4. 监控缓存命中率

---

### 2.2 优化缓存失效策略

**当前问题**: 缓存键包含role，不同角色无法共享缓存

**解决方案**:
```python
# 分离数据缓存和权限过滤
@helmet_router.get("/platform/overview")
def platform_overview(days: int = 7, identity: TrustedIdentity = ...):
    # 数据层缓存（所有角色共享）
    cache_key = f"overview:raw:days={days}"
    raw_data = cache.get(cache_key, CacheTier.SUMMARIES)
    
    if raw_data is None:
        raw_data = build_overview_payload(services.repository, days=days)
        cache.set(cache_key, raw_data, CacheTier.SUMMARIES)
    
    # 权限过滤层（不缓存）
    return filter_by_role(raw_data, identity.role)
```

**验证指标**:
- 缓存命中率: 从 ~40% 提升至 ~75%
- 内存使用: 减少 30%（去重）

---

## 阶段3：前端性能优化 (P1 - 用户体验)

**预计时间**: 3-4天  
**预计性能提升**: 40-50%（感知性能）  
**风险等级**: 低

### 3.1 实现乐观更新与骨架屏

**问题**: 详情页加载时UI冻结

**文件**: `frontend/js/pages/review.js` (行311-320)

**解决方案**:
```javascript
// 方案A: 骨架屏
async function redraw(container) {
    // 立即显示骨架屏
    container.innerHTML = renderSkeleton();
    
    // 异步加载数据
    const detail = await fetchSelectedDetail();
    
    // 数据到达后替换
    container.innerHTML = renderDetail(detail);
}

function renderSkeleton() {
    return `
        <div class="skeleton-card">
            <div class="skeleton-line"></div>
            <div class="skeleton-line"></div>
            <div class="skeleton-image"></div>
        </div>
    `;
}

// 方案B: 乐观更新
function updateAlertStatus(alertId, newStatus) {
    // 立即更新UI
    updateUIOptimistically(alertId, newStatus);
    
    // 后台发送请求
    api.alerts.updateStatus(alertId, newStatus)
        .catch(error => {
            // 失败时回滚
            revertUIUpdate(alertId);
            toast.error('更新失败');
        });
}
```

**实施步骤**:
1. 设计骨架屏CSS（0.5天）
2. 重构数据加载逻辑（1天）
3. 实现乐观更新机制（1天）
4. 添加错误回滚逻辑

---

### 3.2 优化实时数据轮询

**问题**: 固定间隔轮询，后台标签页浪费资源

**文件**: `frontend/js/app.js` (行102)

**解决方案**:
```javascript
// 方案A: 自适应轮询
class AdaptivePoller {
    constructor(fetchFn, baseInterval = 5000) {
        this.fetchFn = fetchFn;
        this.baseInterval = baseInterval;
        this.currentInterval = baseInterval;
        this.consecutiveNoChanges = 0;
    }
    
    async poll() {
        const data = await this.fetchFn();
        
        if (this.hasChanged(data)) {
            // 有变化，加快轮询
            this.currentInterval = this.baseInterval;
            this.consecutiveNoChanges = 0;
        } else {
            // 无变化，逐渐减慢
            this.consecutiveNoChanges++;
            this.currentInterval = Math.min(
                this.baseInterval * Math.pow(1.5, this.consecutiveNoChanges),
                60000  // 最多1分钟
            );
        }
        
        setTimeout(() => this.poll(), this.currentInterval);
    }
}

// 方案B: 后台标签页检测
document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
        // 标签页隐藏，停止轮询
        stopAllPolling();
    } else {
        // 标签页激活，恢复轮询
        resumePolling();
    }
});
```

**验证指标**:
- 网络请求减少: 40-60%
- 后台CPU使用: 降至 <1%

---

### 3.3 虚拟滚动优化大表格

**问题**: 100+行表格渲染卡顿

**文件**: `frontend/js/pages/dashboard.js` (行134-156)

**解决方案**:
```javascript
class VirtualTable {
    constructor(container, data, rowHeight = 50) {
        this.container = container;
        this.data = data;
        this.rowHeight = rowHeight;
        this.visibleRows = Math.ceil(container.clientHeight / rowHeight) + 2;
        this.scrollTop = 0;
        
        this.render();
        this.container.addEventListener('scroll', () => this.onScroll());
    }
    
    render() {
        const startIndex = Math.floor(this.scrollTop / this.rowHeight);
        const endIndex = Math.min(startIndex + this.visibleRows, this.data.length);
        
        // 只渲染可见行
        const visibleData = this.data.slice(startIndex, endIndex);
        const html = visibleData.map(row => this.renderRow(row)).join('');
        
        this.container.innerHTML = `
            <div style="height: ${this.data.length * this.rowHeight}px; position: relative;">
                <div style="transform: translateY(${startIndex * this.rowHeight}px);">
                    ${html}
                </div>
            </div>
        `;
    }
    
    onScroll() {
        this.scrollTop = this.container.scrollTop;
        requestAnimationFrame(() => this.render());
    }
}
```

**验证指标**:
- 1000行表格渲染时间: 从 ~2000ms 降至 <100ms
- 滚动FPS: 从 ~30fps 提升至 60fps

---

## 阶段4：异步处理与队列 (P2 - 可扩展性)

**预计时间**: 4-5天  
**预计性能提升**: 30-40%（吞吐量）  
**风险等级**: 中等

### 4.1 文件上传异步化

**问题**: 同步上传阻塞Alert创建

**文件**: `src/helmet_monitoring/storage/evidence_store.py` (行98-134)

**解决方案**:
```python
# 使用Celery或RQ实现后台任务队列
from celery import Celery

celery_app = Celery('helmet_monitoring', broker='redis://localhost:6379/0')

@celery_app.task(bind=True, max_retries=3)
def upload_evidence_async(self, local_path, object_path, content_type):
    try:
        access_url = supabase_client.storage.from_('evidence').upload(
            object_path,
            open(local_path, 'rb'),
            {'content-type': content_type}
        )
        return access_url
    except Exception as exc:
        # 指数退避重试
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)

# 修改EvidenceStore
class EvidenceStore:
    def save(self, camera_id, frame, artifact_id, created_at, category="alerts"):
        # 立即保存到本地
        local_path = self._local_path(...)
        write_image(local_path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        
        # 异步上传到云端
        task = upload_evidence_async.delay(local_path, object_path, "image/jpeg")
        
        # 返回本地路径，云端URL稍后更新
        return str(local_path), None  # access_url will be updated later
```

**实施步骤**:
1. 安装配置Celery + Redis（1天）
2. 重构EvidenceStore为异步（1.5天）
3. 实现任务状态跟踪
4. 添加失败重试逻辑

**验证指标**:
- Alert创建响应时间: 从 ~1500ms 降至 <200ms
- 上传成功率: 从 ~95% 提升至 ~99.5%（重试机制）

---

### 4.2 实现WebSocket实时推送

**问题**: 轮询无法实现真正实时性

**解决方案**:
```python
# src/helmet_monitoring/api/websocket.py
from fastapi import WebSocket, WebSocketDisconnect

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    
    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            await connection.send_json(message)

manager = ConnectionManager()

@app.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # 保持连接
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.active_connections.remove(websocket)

# 在Alert创建时推送
def create_alert(alert_data):
    alert = repository.insert_alert(alert_data)
    # 实时推送给所有连接的客户端
    asyncio.create_task(manager.broadcast({
        'type': 'alert_created',
        'data': alert
    }))
    return alert
```

**前端集成**:
```javascript
// frontend/js/websocket.js
class AlertWebSocket {
    constructor() {
        this.ws = new WebSocket('ws://localhost:8000/ws/alerts');
        this.ws.onmessage = (event) => this.handleMessage(event);
    }
    
    handleMessage(event) {
        const message = JSON.parse(event.data);
        if (message.type === 'alert_created') {
            // 实时更新UI
            prependAlertToList(message.data);
            showNotification('新告警', message.data.camera_name);
        }
    }
}
```

**验证指标**:
- 实时性延迟: 从 5-30秒 降至 <500ms
- 网络请求减少: 80%

---

## 阶段5：监控与可观测性 (P3 - 运维)

**预计时间**: 2-3天  
**风险等级**: 低

### 5.1 性能监控仪表板

**实施内容**:
```python
# src/helmet_monitoring/api/metrics.py
from prometheus_client import Counter, Histogram, Gauge

# 定义指标
api_requests_total = Counter('api_requests_total', 'Total API requests', ['endpoint', 'method', 'status'])
api_request_duration = Histogram('api_request_duration_seconds', 'API request duration', ['endpoint'])
cache_hit_rate = Gauge('cache_hit_rate', 'Cache hit rate', ['tier'])
db_query_duration = Histogram('db_query_duration_seconds', 'Database query duration', ['operation'])

# 中间件
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    
    api_requests_total.labels(
        endpoint=request.url.path,
        method=request.method,
        status=response.status_code
    ).inc()
    
    api_request_duration.labels(endpoint=request.url.path).observe(duration)
    
    return response

# 暴露指标端点
@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
```

**集成Grafana仪表板**:
- API响应时间分布
- 缓存命中率趋势
- 数据库查询性能
- 错误率监控

---

## 实施优先级矩阵

| 阶段 | 优先级 | 工作量 | 性能提升 | 风险 | 建议顺序 |
|------|--------|--------|----------|------|----------|
| 数据库查询优化 | P0 | 3-4天 | 70-80% | 中 | 1 |
| 缓存策略增强 | P1 | 2-3天 | 50-60% | 低 | 2 |
| 前端性能优化 | P1 | 3-4天 | 40-50% | 低 | 3 |
| 异步处理与队列 | P2 | 4-5天 | 30-40% | 中 | 4 |
| 监控与可观测性 | P3 | 2-3天 | N/A | 低 | 5 |

**总计**: 14-19天工作量，预计整体性能提升60-80%

---

## 快速启动方案（1周内见效）

如果时间有限，建议优先实施以下3项：

### 快速方案1: 数据库索引（2天）
- 实现LocalAlertRepository内存索引
- 立即见效，风险低

### 快速方案2: 缓存预热（1天）
- 添加启动时缓存预热
- 优化缓存键策略
- 提升缓存命中率

### 快速方案3: 前端骨架屏（1天）
- 实现关键页面骨架屏
- 显著改善感知性能
- 无需后端改动

**快速方案总计**: 4天，预计性能提升40-50%

---

## 性能基准测试计划

### 测试场景
1. **仪表板加载**: 测量首页完整加载时间
2. **告警列表分页**: 测量100/1000/10000条数据下的响应时间
3. **详情页加载**: 测量单个告警详情的加载时间
4. **并发压力**: 使用Locust模拟100并发用户

### 基准指标（优化前）
```
仪表板加载: ~800ms
告警列表(1000条): ~500ms
详情页加载: ~300ms
100并发RPS: ~50
```

### 目标指标（优化后）
```
仪表板加载: <200ms (75%提升)
告警列表(1000条): <100ms (80%提升)
详情页加载: <100ms (67%提升)
100并发RPS: >150 (200%提升)
```

---

## 风险评估与缓解

### 高风险项
1. **数据库迁移到SQLite**
   - 风险: 数据丢失、兼容性问题
   - 缓解: 保留JSONL备份，灰度发布

2. **异步文件上传**
   - 风险: 任务队列故障导致上传失败
   - 缓解: 实现降级机制，失败时回退到同步上传

### 中风险项
1. **缓存策略变更**
   - 风险: 缓存不一致导致数据错误
   - 缓解: 严格的缓存失效逻辑，添加版本号

2. **WebSocket实现**
   - 风险: 连接管理复杂，内存泄漏
   - 缓解: 连接数限制，定期清理断开连接

---

## 下一步行动

1. **评审本路线图**，确认优先级和时间表
2. **选择实施方案**：
   - 完整路线图（14-19天）
   - 快速启动方案（4天）
3. **建立性能基准**，记录优化前指标
4. **开始阶段1实施**，从数据库查询优化开始

---

**文档版本**: v1.0  
**创建日期**: 2026-04-XX  
**负责人**: [待指定]  
**审核状态**: 待审核
