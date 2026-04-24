# 优化模块测试验证指南

本文档提供完整的测试验证流程，确保所有优化模块正常工作。

---

## 测试环境准备

### 1. 安装测试依赖

```bash
pip install pytest pytest-asyncio pytest-benchmark locust
```

### 2. 准备测试数据

```bash
# 生成10000条测试告警数据
python tests/performance/generate_test_data.py --count 10000
```

### 3. 启动应用

```bash
# 开发模式
uvicorn helmet_monitoring.api.app:app --reload --port 8000

# 生产模式
gunicorn helmet_monitoring.api.app:app -w 4 -k uvicorn.workers.UvicornWorker
```

---

## 单元测试

### 测试1: 缓存管理器

```python
# tests/unit/test_cache_manager.py
import pytest
from helmet_monitoring.api.cache_manager import CacheManager, CacheTier

def test_cache_basic_operations():
    """测试基本缓存操作"""
    cache = CacheManager(max_entries=100)
    
    # Set & Get
    cache.set("key1", {"data": "value1"}, CacheTier.REALTIME)
    assert cache.get("key1", CacheTier.REALTIME) == {"data": "value1"}
    
    # 统计
    stats = cache.get_stats()
    assert stats['total_sets'] == 1
    assert stats['total_gets'] == 1
    assert stats['hits'] == 1
    assert stats['hit_rate'] == 1.0


def test_cache_expiration():
    """测试缓存过期"""
    import time
    cache = CacheManager()
    
    # REALTIME层5秒过期
    cache.set("key1", "value1", CacheTier.REALTIME)
    assert cache.get("key1", CacheTier.REALTIME) == "value1"
    
    time.sleep(6)
    assert cache.get("key1", CacheTier.REALTIME) is None


def test_cache_invalidation():
    """测试缓存失效"""
    cache = CacheManager()
    
    cache.set(("alerts", "list", "camera=1"), [1, 2, 3], CacheTier.SUMMARIES)
    cache.set(("alerts", "list", "camera=2"), [4, 5, 6], CacheTier.SUMMARIES)
    cache.set(("overview", "days=7"), {"total": 100}, CacheTier.SUMMARIES)
    
    # 模式匹配失效
    cache.invalidate_pattern("alerts:*")
    
    assert cache.get(("alerts", "list", "camera=1"), CacheTier.SUMMARIES) is None
    assert cache.get(("alerts", "list", "camera=2"), CacheTier.SUMMARIES) is None
    assert cache.get(("overview", "days=7"), CacheTier.SUMMARIES) is not None


def test_cache_lru_eviction():
    """测试LRU淘汰"""
    cache = CacheManager(max_entries=3)
    
    cache.set("key1", "value1", CacheTier.STATIC)
    cache.set("key2", "value2", CacheTier.STATIC)
    cache.set("key3", "value3", CacheTier.STATIC)
    
    # 访问key1，使其成为最近使用
    cache.get("key1", CacheTier.STATIC)
    
    # 添加key4，应该淘汰key2（最久未使用）
    cache.set("key4", "value4", CacheTier.STATIC)
    
    assert cache.get("key1", CacheTier.STATIC) == "value1"
    assert cache.get("key2", CacheTier.STATIC) is None
    assert cache.get("key4", CacheTier.STATIC) == "value4"
```

运行测试：
```bash
pytest tests/unit/test_cache_manager.py -v
```

预期结果：
```
test_cache_basic_operations PASSED
test_cache_expiration PASSED
test_cache_invalidation PASSED
test_cache_lru_eviction PASSED
```

---

### 测试2: 索引Repository

```python
# tests/unit/test_indexed_repository.py
import pytest
from pathlib import Path
from helmet_monitoring.storage.indexed_repository import IndexedLocalAlertRepository

@pytest.fixture
def repository(tmp_path):
    """创建临时Repository"""
    return IndexedLocalAlertRepository(tmp_path)


def test_index_building(repository):
    """测试索引构建"""
    # 添加测试数据
    alert1 = repository.create_alert({
        "camera_id": "cam1",
        "status": "pending",
        "timestamp": "2026-04-24T10:00:00Z"
    })
    
    alert2 = repository.create_alert({
        "camera_id": "cam2",
        "status": "resolved",
        "timestamp": "2026-04-24T11:00:00Z"
    })
    
    # 验证索引
    assert len(repository._camera_index["cam1"]) == 1
    assert len(repository._camera_index["cam2"]) == 1
    assert len(repository._alert_cache) == 2


def test_indexed_query_performance(repository, benchmark):
    """测试索引查询性能"""
    # 创建1000条测试数据
    for i in range(1000):
        repository.create_alert({
            "camera_id": f"cam{i % 10}",
            "status": "pending",
            "timestamp": f"2026-04-24T{i % 24:02d}:00:00Z"
        })
    
    # 基准测试
    result = benchmark(repository.list_alerts, camera_id="cam1", limit=100)
    
    # 验证结果
    assert len(result) <= 100
    assert all(a['camera_id'] == 'cam1' for a in result)


def test_incremental_index_update(repository):
    """测试增量索引更新"""
    alert = repository.create_alert({
        "camera_id": "cam1",
        "status": "pending"
    })
    
    alert_id = alert['alert_id']
    
    # 更新状态
    repository.update_alert_status(alert_id, "resolved")
    
    # 验证索引更新
    updated = repository.get_alert(alert_id)
    assert updated['status'] == 'resolved'
```

运行测试：
```bash
pytest tests/unit/test_indexed_repository.py -v --benchmark-only
```

---

### 测试3: 异步任务系统

```python
# tests/unit/test_task_queue.py
import pytest
import time
from helmet_monitoring.tasks.task_queue import SimpleTaskQueue, async_task

def test_task_execution():
    """测试任务执行"""
    queue = SimpleTaskQueue(num_workers=2)
    
    @async_task(queue=queue)
    def add(a, b):
        return a + b
    
    # 提交任务
    task_id = add.delay(1, 2)
    
    # 等待完成
    time.sleep(0.5)
    
    # 获取结果
    result = queue.get_result(task_id)
    assert result['status'] == 'completed'
    assert result['result'] == 3


def test_task_retry():
    """测试任务重试"""
    queue = SimpleTaskQueue(num_workers=1)
    
    attempt_count = 0
    
    @async_task(queue=queue, max_retries=3)
    def flaky_task():
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count < 3:
            raise Exception("Temporary failure")
        return "success"
    
    task_id = flaky_task.delay()
    time.sleep(2)
    
    result = queue.get_result(task_id)
    assert result['status'] == 'completed'
    assert result['result'] == 'success'
    assert attempt_count == 3


def test_queue_stats():
    """测试队列统计"""
    queue = SimpleTaskQueue(num_workers=2)
    
    @async_task(queue=queue)
    def slow_task():
        time.sleep(0.1)
        return "done"
    
    # 提交多个任务
    for _ in range(5):
        slow_task.delay()
    
    stats = queue.get_stats()
    assert stats['total_submitted'] == 5
    assert stats['num_workers'] == 2
```

---

## 集成测试

### 测试4: API端点性能

```python
# tests/integration/test_api_performance.py
import pytest
from fastapi.testclient import TestClient
from helmet_monitoring.api.app import create_app

@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_list_alerts_with_cache(client, benchmark):
    """测试告警列表（带缓存）"""
    def fetch_alerts():
        response = client.get("/api/v1/alerts?limit=100")
        assert response.status_code == 200
        return response.json()
    
    # 第一次请求（缓存未命中）
    result1 = benchmark(fetch_alerts)
    
    # 第二次请求（缓存命中）
    result2 = fetch_alerts()
    
    assert result1 == result2


def test_platform_overview_optimized(client, benchmark):
    """测试优化的仪表板"""
    def fetch_overview():
        response = client.get("/api/v1/platform-overview?days=7")
        assert response.status_code == 200
        return response.json()
    
    result = benchmark(fetch_overview)
    
    # 验证数据结构
    assert 'total_alerts' in result
    assert 'by_status' in result
    assert 'by_department' in result


def test_cache_invalidation_on_update(client):
    """测试更新时缓存失效"""
    # 获取告警列表（填充缓存）
    response1 = client.get("/api/v1/alerts?limit=10")
    alerts = response1.json()
    
    if alerts:
        alert_id = alerts[0]['alert_id']
        
        # 更新状态
        response2 = client.post(
            f"/api/v1/alerts/{alert_id}/status",
            json={"status": "resolved"}
        )
        assert response2.status_code == 200
        
        # 再次获取列表（应该看到更新）
        response3 = client.get("/api/v1/alerts?limit=10")
        updated_alerts = response3.json()
        
        updated_alert = next(a for a in updated_alerts if a['alert_id'] == alert_id)
        assert updated_alert['status'] == 'resolved'
```

---

### 测试5: WebSocket实时推送

```python
# tests/integration/test_websocket.py
import pytest
import asyncio
from fastapi.testclient import TestClient
from helmet_monitoring.api.app import create_app

@pytest.mark.asyncio
async def test_websocket_alert_broadcast():
    """测试告警广播"""
    app = create_app()
    client = TestClient(app)
    
    with client.websocket_connect("/ws/alerts") as websocket:
        # 创建新告警
        response = client.post("/api/v1/alerts", json={
            "camera_id": "cam1",
            "type": "no_helmet",
            "timestamp": "2026-04-24T10:00:00Z"
        })
        
        # 接收WebSocket消息
        data = websocket.receive_json(timeout=5)
        
        assert data['type'] == 'alert_created'
        assert data['data']['camera_id'] == 'cam1'


@pytest.mark.asyncio
async def test_websocket_reconnection():
    """测试WebSocket重连"""
    app = create_app()
    client = TestClient(app)
    
    # 第一次连接
    with client.websocket_connect("/ws/alerts") as ws1:
        ws1.send_json({"type": "ping"})
        response = ws1.receive_json()
        assert response['type'] == 'pong'
    
    # 重新连接
    with client.websocket_connect("/ws/alerts") as ws2:
        ws2.send_json({"type": "ping"})
        response = ws2.receive_json()
        assert response['type'] == 'pong'
```

---

## 性能基准测试

### 运行完整基准测试

```bash
cd tests/performance
python benchmark.py
```

预期输出：
```
=== Performance Benchmark Report ===

1. Database Query Performance
   Standard Repository - List Alerts: 485.23ms (avg)
   Indexed Repository - List Alerts: 42.15ms (avg)
   Improvement: 91.3%

2. Dashboard Aggregation
   Standard Aggregation: 823.45ms (avg)
   Optimized Aggregation: 98.67ms (avg)
   Improvement: 88.0%

3. Cache Performance
   Cache Set: 0.15ms (avg)
   Cache Get (Hit): 0.08ms (avg)
   Cache Get (Miss): 0.12ms (avg)
   Hit Rate: 75.3%

4. API Endpoints
   GET /api/v1/alerts: 45.23ms (avg)
   GET /api/v1/platform-overview: 112.34ms (avg)
   GET /api/v1/cameras: 67.89ms (avg)

Overall Performance Improvement: 60-80%
```

---

## 负载测试

### 使用Locust进行负载测试

创建 `tests/load/locustfile.py`:

```python
from locust import HttpUser, task, between

class HelmetMonitoringUser(HttpUser):
    wait_time = between(1, 3)
    
    @task(3)
    def list_alerts(self):
        """列出告警（高频）"""
        self.client.get("/api/v1/alerts?limit=50")
    
    @task(2)
    def get_overview(self):
        """获取概览（中频）"""
        self.client.get("/api/v1/platform-overview?days=7")
    
    @task(1)
    def get_cameras(self):
        """获取摄像头列表（低频）"""
        self.client.get("/api/v1/cameras")
    
    @task(1)
    def get_alert_detail(self):
        """获取告警详情（低频）"""
        # 先获取列表
        response = self.client.get("/api/v1/alerts?limit=1")
        alerts = response.json()
        
        if alerts:
            alert_id = alerts[0]['alert_id']
            self.client.get(f"/api/v1/alerts/{alert_id}")
```

运行负载测试：
```bash
locust -f tests/load/locustfile.py --host=http://localhost:8000
```

访问 `http://localhost:8089` 配置：
- 用户数: 100
- 增长速率: 10/秒

预期结果：
- RPS: >150
- P95延迟: <200ms
- 错误率: <1%

---

## 监控验证

### 1. Prometheus指标

访问 `http://localhost:8000/metrics`，验证以下指标：

```
# API请求指标
api_request_duration_seconds_bucket{endpoint="/api/v1/alerts",le="0.1"} 850
api_request_duration_seconds_bucket{endpoint="/api/v1/alerts",le="0.5"} 980
api_request_total{endpoint="/api/v1/alerts",status="200"} 1000

# 缓存指标
cache_hit_rate{tier="summaries"} 0.753
cache_size_bytes 1048576
cache_operations_total{operation="get",result="hit"} 753

# 任务队列指标
task_queue_size 5
task_execution_duration_seconds_sum 12.34
task_execution_total{status="completed"} 95
```

### 2. 缓存统计

```bash
curl http://localhost:8000/ops/cache/stats
```

预期响应：
```json
{
  "total_entries": 245,
  "total_sets": 1000,
  "total_gets": 3000,
  "hits": 2250,
  "misses": 750,
  "hit_rate": 0.75,
  "invalidations": 12,
  "by_tier": {
    "REALTIME": {"entries": 50, "hit_rate": 0.65},
    "SUMMARIES": {"entries": 120, "hit_rate": 0.78},
    "STATIC": {"entries": 75, "hit_rate": 0.82}
  }
}
```

### 3. 任务队列统计

```bash
curl http://localhost:8000/ops/tasks/stats
```

预期响应：
```json
{
  "queue_size": 5,
  "num_workers": 2,
  "total_submitted": 150,
  "total_completed": 142,
  "total_failed": 3,
  "avg_execution_time": 0.234
}
```

### 4. WebSocket统计

```bash
curl http://localhost:8000/ops/websocket/stats
```

预期响应：
```json
{
  "total_connections": 25,
  "active_connections": 25,
  "total_messages_sent": 1250,
  "by_topic": {
    "alerts": 15,
    "dashboard": 10
  }
}
```

---

## 前端性能测试

### 使用Chrome DevTools

1. 打开 Chrome DevTools (F12)
2. 切换到 Performance 标签
3. 点击 Record 开始录制
4. 执行以下操作：
   - 加载告警列表页面
   - 滚动列表
   - 点击告警详情
   - 更新告警状态
5. 停止录制并分析

预期指标：
- FCP (First Contentful Paint): <1s
- LCP (Largest Contentful Paint): <2.5s
- FID (First Input Delay): <100ms
- CLS (Cumulative Layout Shift): <0.1
- 滚动FPS: 60fps

### 使用Lighthouse

```bash
# 安装Lighthouse
npm install -g lighthouse

# 运行测试
lighthouse http://localhost:8000 --output html --output-path ./lighthouse-report.html
```

预期分数：
- Performance: >90
- Accessibility: >95
- Best Practices: >90
- SEO: >90

---

## 验收清单

### 功能验证

- [ ] 告警列表正常加载
- [ ] 告警详情正常显示
- [ ] 状态更新正常工作
- [ ] 仪表板数据正确
- [ ] 摄像头列表正常
- [ ] 人员列表正常
- [ ] 缓存正常工作
- [ ] 任务队列正常运行
- [ ] WebSocket连接成功
- [ ] Prometheus指标可访问

### 性能验证

- [ ] 告警列表查询 <100ms
- [ ] 仪表板加载 <200ms
- [ ] 缓存命中率 >70%
- [ ] 100并发RPS >150
- [ ] P95延迟 <200ms
- [ ] 错误率 <1%

### 监控验证

- [ ] Prometheus指标正常采集
- [ ] 缓存统计准确
- [ ] 任务队列统计准确
- [ ] WebSocket统计准确
- [ ] Grafana仪表板正常显示

### 前端验证

- [ ] FCP <1s
- [ ] LCP <2.5s
- [ ] FID <100ms
- [ ] 滚动流畅 60fps
- [ ] 骨架屏正常显示
- [ ] 乐观更新正常工作
- [ ] 虚拟滚动正常工作

---

## 故障模拟测试

### 1. 缓存失效测试

```python
# 清空缓存
cache.clear_all()

# 验证系统仍然正常工作（降级到数据库查询）
response = client.get("/api/v1/alerts")
assert response.status_code == 200
```

### 2. 任务队列故障测试

```python
# 停止任务队列
queue.shutdown()

# 验证API仍然响应（任务失败但不阻塞）
response = client.post("/api/v1/alerts", json={...})
assert response.status_code == 200
```

### 3. WebSocket断连测试

```javascript
// 模拟网络断开
websocket.close();

// 验证自动重连
setTimeout(() => {
    assert(websocket.readyState === WebSocket.OPEN);
}, 6000);
```

---

## 回归测试

每次修改后运行完整测试套件：

```bash
# 单元测试
pytest tests/unit/ -v

# 集成测试
pytest tests/integration/ -v

# 性能测试
python tests/performance/benchmark.py

# 负载测试
locust -f tests/load/locustfile.py --headless -u 100 -r 10 --run-time 5m
```

---

## 测试报告模板

```markdown
# 测试报告

**测试日期**: 2026-04-24
**测试人员**: [姓名]
**测试环境**: [开发/测试/生产]

## 测试结果

### 单元测试
- 通过: 45/45
- 失败: 0
- 覆盖率: 85%

### 集成测试
- 通过: 12/12
- 失败: 0

### 性能测试
- 告警列表: 45ms (目标<100ms) ✅
- 仪表板: 112ms (目标<200ms) ✅
- 缓存命中率: 75.3% (目标>70%) ✅

### 负载测试
- RPS: 165 (目标>150) ✅
- P95延迟: 187ms (目标<200ms) ✅
- 错误率: 0.3% (目标<1%) ✅

## 问题列表
无

## 结论
所有测试通过，系统满足性能要求，可以部署到生产环境。
```

---

**文档版本**: 1.0  
**最后更新**: 2026-04-24
