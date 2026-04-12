# Safety Helmet Detection System

## English Version

### Overview

This repository is a product-style safety helmet detection system built around a YOLO-based detector, a monitoring worker, and an operations console.

It supports:

- Local webcam monitoring
- Browser-based live camera preview with real-time red/green boxes
- Desktop real-time viewer with smoother local rendering
- RTSP / HTTP / RTMP stream monitoring
- Streamlit operations dashboard
- Supabase-backed alert storage and review workflow
- Optional OCR and face-recognition extensions
- Hard-case collection for later model improvement

In the current implementation:

- Green box = helmet detected
- Red box = no helmet detected / violation

### What Is In This Repository

The project contains three major runtime paths:

1. Browser camera preview for the local webcam
   This is the recommended path when you want a smoother local live view in the browser.

2. Desktop real-time viewer for the local webcam
   This is useful when you want an even more direct local preview window without going through the web dashboard.

3. Docker-based stream monitoring
   This is intended for RTSP / HTTP / RTMP inputs such as phone-published streams or industrial cameras.

### Main Components

- `app.py`
  Streamlit operations console.

- `src/helmet_monitoring/services/detector.py`
  Helmet detection pipeline wrapper.

- `src/helmet_monitoring/services/monitor.py`
  Continuous monitoring worker used for stream-style inputs.

- `src/helmet_monitoring/ui/live_preview_stream.py`
  Lightweight preview server that exposes:
  - `/health`
  - `/browser/<camera_id>` for browser camera preview
  - `/infer/<camera_id>` for browser-frame inference
  - `/mjpeg/<camera_id>` for MJPEG live preview

- `scripts/browser_camera_preview.py`
  Starts the lightweight browser preview service and opens the browser automatically.

- `scripts/realtime_camera_viewer.py`
  Starts a local desktop viewer using Tkinter + OpenCV with live red/green boxes.

- `scripts/run_monitor.py`
  Starts the monitoring worker.

- `docker-compose.yml`
  Docker stack for the dashboard, RTMP gateway, and monitoring worker.

### Repository Layout

```text
safety_helmet_yolo26/
├─ app.py                             # Streamlit operations console entry
├─ docker-compose.yml                 # Dashboard + monitor + RTMP relay stack
├─ configs/
│  ├─ runtime.json                    # Active runtime configuration
│  └─ runtime.example.json            # Runtime configuration template
├─ scripts/
│  ├─ start_desktop_webcam.cmd        # Browser local-webcam demo launcher
│  ├─ start_realtime_webcam.cmd       # Desktop real-time viewer launcher
│  ├─ start_stream_docker.cmd         # Docker stream-mode launcher
│  ├─ start_dashboard_service.cmd     # Managed dashboard service launcher
│  ├─ start_monitor_service.cmd       # Managed monitor service launcher
│  ├─ start_host_services.cmd         # Launch both managed services
│  ├─ doctor.py                       # Environment and dependency diagnostics
│  ├─ check_supabase.py               # Supabase readiness checker
│  ├─ smoke_product.py                # End-to-end smoke tests
│  ├─ validate_notification_delivery.py # Independent notification delivery validation
│  ├─ bootstrap_identity_defaults.py  # Suggest/apply default people for cameras
│  ├─ identity_delivery_audit.py      # Identity data coverage audit
│  ├─ dashboard_healthcheck.py        # Dashboard health probe
│  ├─ monitor_healthcheck.py          # Monitor worker health probe
│  └─ install_windows_autostart.ps1   # Install Windows scheduled-task auto-start
├─ src/
│  └─ helmet_monitoring/              # Core package (detection + monitoring + UI services)
├─ sql/                               # Supabase schema and extension scripts
├─ tests/                             # Automated tests
├─ artifacts/                         # Runtime outputs (captures, alerts, training, backups)
└─ docs/                              # Productization and operations references
```

### Supported Runtime

- Recommended Python: `3.11`
- Supported fallback Python: `3.10`

Create the environment:

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements.identity.txt
.venv\Scripts\python.exe -m pip install -r requirements.dev.txt
```

### Initial Setup

Bootstrap the workspace:

```bash
.venv\Scripts\python.exe scripts/bootstrap_workspace.py --copy-env-example --copy-registry-example
```

Run a readiness inspection:

```bash
.venv\Scripts\python.exe scripts/doctor.py --ensure-scaffold
```

Optional strict deployment inspection:

```bash
.venv\Scripts\python.exe scripts/doctor.py --deploy-strict
```

### Environment Configuration

Create `.env` from `configs/supabase.example.env` and then fill in your real values.

Important variables:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_STORAGE_BUCKET`
- `HELMET_CONFIG_PATH`
- `HELMET_PUBLISH_URL`
- `HELMET_MONITOR_STREAM_URL`
- `camera_use_laptop_camera=true`
- `HELMET_LIVE_PREVIEW_PORT`
- `OPENAI_API_KEY`
- `DEEPSEEK_API_KEY`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM_EMAIL`
- `ALERT_EMAIL_RECIPIENTS`
- `HELMET_AUTH_USERS_FILE`
- `HELMET_AUTH_ADMIN_USERNAME`
- `HELMET_AUTH_ADMIN_PASSWORD_HASH`

Notes:

- `camera_use_laptop_camera=true` forces local-webcam demo behavior during settings loading.
- `HELMET_LIVE_PREVIEW_PORT` defaults to `8876`.
- Do not commit real secrets to version control.
- If any keys were exposed during development, rotate them before production use.

### Runtime Configuration

The main runtime file is `configs/runtime.json`.

Important sections:

- `model`
  - `path`: model path
  - `confidence`: detection threshold
  - `imgsz`: inference image size
  - `device`: inference device such as `cpu`
  - `safe_labels`: labels treated as safe
  - `violation_labels`: labels treated as violations

- `monitoring`
  - `frame_stride`
  - `preview_fps`
  - `camera_retry_seconds`
  - `heartbeat_interval_seconds`
  - `max_frames`

- `cameras`
  - `camera_id`
  - `camera_name`
  - `source`
  - `enabled`

- `security`
  - `evidence_retention_days`
  - `signed_url_seconds`

Current preview-related behavior:

- `monitoring.preview_fps` defaults to `20.0`
- browser preview draws green boxes for safe detections
- browser preview draws red boxes for violations

### Recommended Startup Modes

#### 1. Browser Camera Preview for Local Webcam

This is the recommended mode if you want live webcam output that feels closer to real video in the browser.

Launch:

```bash
start_desktop_webcam.cmd
```

What it does now:

- starts the lightweight local preview service
- opens the browser automatically
- uses the browser camera directly
- sends frames to the local inference endpoint
- overlays green/red boxes on top of the live video

Manual launch:

```bash
.venv\Scripts\python.exe scripts/browser_camera_preview.py
```

Default preview URL pattern:

```text
http://127.0.0.1:8876/browser/<camera_id>
```

Example:

```text
http://127.0.0.1:8876/browser/cam-local-001
```

Important requirements:

- the browser must allow camera permission
- use `localhost`, `127.0.0.1`, or HTTPS
- another application must not lock the webcam

#### 2. Desktop Real-Time Viewer

Use this mode if you want a local desktop window instead of a browser page.

Launch:

```bash
start_realtime_webcam.cmd
```

Manual launch:

```bash
.venv\Scripts\python.exe scripts/realtime_camera_viewer.py --source 0
```

Useful tuning examples:

```bash
.venv\Scripts\python.exe scripts/realtime_camera_viewer.py --source 0 --imgsz 256 --detect-interval-ms 100
.venv\Scripts\python.exe scripts/realtime_camera_viewer.py --source 0 --camera-width 1280 --camera-height 720
```

How it works:

- background thread continuously reads the latest frame
- detector runs on an interval
- last detection is briefly reused to keep motion smoother
- green box means helmet
- red box means no helmet

Close methods:

- close the window
- press `Esc`
- press `q`

#### 3. Streamlit Operations Console

Use this mode for operations, review, reporting, and administration.

Run locally:

```bash
set YOLO_CONFIG_DIR=%CD%\.ultralytics
.venv\Scripts\streamlit.exe run app.py
```

Default URL:

```text
http://localhost:8501
```

Best use cases:

- review alerts
- view camera status
- manage metadata
- export reports
- inspect notifications

This dashboard is not the best path when your only goal is the smoothest local webcam preview. For that, prefer the browser camera preview or the desktop real-time viewer above.

#### 4. Docker Stream Mode

Use this mode for stream-based sources such as:

- RTSP cameras
- HTTP video streams
- phone camera apps pushing RTMP

Launch:

```bash
start_stream_docker.cmd
```

Equivalent manual command:

```bash
docker compose up -d --build
```

Default services:

- `dashboard`
- `monitor`
- `rtmp-gateway`

Optional edge profile:

```bash
docker compose --profile edge up -d --build
```

Recommended RTMP flow:

1. your phone pushes RTMP to `HELMET_PUBLISH_URL`
2. the in-cluster relay is `rtmp://rtmp-gateway:1935/live/stream`
3. the Docker monitor reads `HELMET_MONITOR_STREAM_URL`

### Database Setup

Run these SQL files in Supabase SQL Editor in order:

1. `sql/supabase_phase1_schema.sql`
2. `sql/supabase_identity_extension.sql`
3. `sql/supabase_identity_delivery_extension.sql`
4. `sql/supabase_identity_ai_extension.sql`
5. `sql/supabase_product_extension.sql`

Then verify:

```bash
.venv\Scripts\python.exe scripts/check_supabase.py
```

Expected signals:

- `identity_extension=ready`
- `identity_ai_extension=ready`
- `product_extension=ready`
- `storage_bucket_ready=true`

If the output says local backend or missing credentials, the project is still running in local fallback mode.

### Optional Identity Stack

Install optional packages:

```bash
.venv\Scripts\python.exe -m pip install -r requirements.identity.txt
```

Register local face profiles:

1. Put images into `artifacts/identity/faces/<person_id>/`
2. Run:

```bash
.venv\Scripts\python.exe scripts/register_face_profiles.py
```

Sync the registry:

```bash
.venv\Scripts\python.exe scripts/sync_person_registry.py
```

### Smoke Tests and Validation

Run local smoke:

```bash
.venv\Scripts\python.exe scripts/smoke_product.py
```

Run model-backed smoke:

```bash
.venv\Scripts\python.exe scripts/smoke_product.py --use-model
```

Run strict validation:

```bash
.venv\Scripts\python.exe scripts/smoke_product.py --strict-runtime --use-model --require-model-detection --final-status ignored
```

Run notification-only validation:

```bash
.venv\Scripts\python.exe scripts/validate_notification_delivery.py --mode dry_run
.venv\Scripts\python.exe scripts/validate_notification_delivery.py --mode smtp --require-success --recipient your@email.com
.venv\Scripts\python.exe scripts/validate_notification_delivery.py --mode smtp --require-success --local-runtime-dir %TEMP%\helmet_notify_check
```

Audit identity coverage and default-person readiness:

```bash
.venv\Scripts\python.exe scripts/enrich_identity_registry.py --write
.venv\Scripts\python.exe scripts/identity_delivery_audit.py
.venv\Scripts\python.exe scripts/bootstrap_identity_defaults.py
```

Validate Supabase Storage upload / signed URL / cleanup:

```bash
.venv\Scripts\python.exe scripts/validate_storage_delivery.py --require-success
```

Run tests:

```bash
.venv\Scripts\python.exe -m pytest -q
```

Useful checks:

```bash
.venv\Scripts\python.exe scripts/dashboard_healthcheck.py
.venv\Scripts\python.exe scripts/monitor_healthcheck.py
.venv\Scripts\python.exe scripts/ops_status.py --json
```

Managed local services:

```bash
start_dashboard_service.cmd
start_monitor_service.cmd
start_host_services.cmd
```

Install Windows auto-start tasks:

```bash
install_windows_autostart.cmd
uninstall_windows_autostart.cmd
```

The installer prefers Windows Scheduled Tasks and automatically falls back to the user Startup folder when logon-task creation is blocked.

### Product Scope

Current product-style capabilities include:

- multi-source video ingestion
- helmet / no-helmet detection
- tracking and event judgment
- OCR and face-resolution extensions
- alert review workflow
- evidence snapshots and clips
- camera management
- notifications and logs
- reporting and export
- hard-case collection for retraining

### Backup, Restore, and Release

Create a backup:

```bash
.venv\Scripts\python.exe scripts/backup_system.py --name ops-baseline
```

Restore a backup:

```bash
.venv\Scripts\python.exe scripts/restore_system.py artifacts\backups\ops-baseline.zip
```

Create and activate a release snapshot:

```bash
.venv\Scripts\python.exe scripts/release_manager.py snapshot --name baseline-runtime --activate
```

Rollback:

```bash
.venv\Scripts\python.exe scripts/release_manager.py rollback --steps 1
```

### Model Feedback Loop

Export feedback:

```bash
.venv\Scripts\python.exe scripts/model_feedback_loop.py export-feedback
```

Build a merged dataset:

```bash
.venv\Scripts\python.exe scripts/model_feedback_loop.py build-dataset
```

Register and promote a model:

```bash
.venv\Scripts\python.exe scripts/model_feedback_loop.py register-model artifacts\training_runs\helmet_project\cpu_test3\weights\best.pt
.venv\Scripts\python.exe scripts/model_feedback_loop.py promote-model --model-path artifacts\training_runs\helmet_project\cpu_test3\weights\best.pt
```

Run a full cycle:

```bash
.venv\Scripts\python.exe scripts/model_feedback_loop.py full-cycle --train --promote
```

### Troubleshooting

#### Browser preview does not open automatically

- manually open the URL printed in the terminal
- default port is usually `8876`
- check whether another process is already using the preview port

#### Browser preview opens but no camera image appears

- allow browser camera permission
- close other camera applications
- confirm that a local camera is enabled in configuration
- confirm that `camera_use_laptop_camera=true` is set when you want local webcam mode

#### `localhost:8501` shows a blank or skeleton page

- wait for Streamlit to finish loading
- rebuild and restart the dashboard if you are using Docker:

```bash
docker compose up -d --build dashboard
```

- if your goal is smooth live webcam preview, use `start_desktop_webcam.cmd` instead of relying on the heavy dashboard page

#### Docker cannot read the webcam

This is expected on many Windows setups. Use one of these instead:

- browser camera preview
- desktop real-time viewer
- RTSP / RTMP stream mode

#### Preview is not smooth enough

Try one or more of the following:

- use browser camera preview instead of the Streamlit dashboard
- use the desktop real-time viewer
- reduce `imgsz`
- increase `detect-interval-ms`
- close other CPU-heavy applications
- move from CPU to GPU if available

### Additional References

- `docs/industrialization_blueprint.md`
- `docs/productization_checklist.md`
- `docs/model_training_plan.md`
- `docs/keys_and_services_checklist.md`

---

## 中文版本

### 项目简介

这个仓库是一套基于 YOLO 的安全帽检测系统，包含检测模型、监控 worker、实时预览能力，以及 Streamlit 运维控制台。

当前系统支持：

- 本地摄像头检测
- 浏览器实时摄像头预览，并叠加红框 / 绿框
- 本地桌面实时预览窗口
- RTSP / HTTP / RTMP 视频流检测
- Streamlit 运维与告警管理后台
- Supabase 告警存储与闭环流程
- 可选的人脸识别与 OCR 扩展
- Hard Case 采集与后续模型迭代

当前颜色规则：

- 绿色框：检测到已佩戴安全帽
- 红色框：检测到未佩戴安全帽或违规目标

### 仓库里现在有什么

这个项目现在主要有三条运行路径：

1. 本地浏览器摄像头预览
   这是本地摄像头场景下最推荐的方式，画面更接近“视频实时预览”。

2. 本地桌面实时预览窗口
   适合想直接弹出本地窗口、不经过网页重页面的场景。

3. Docker 流媒体监控模式
   适合 RTSP / HTTP / RTMP 输入，例如手机推流或工业摄像头。

### 核心组件

- `app.py`
  Streamlit 运维控制台入口。

- `src/helmet_monitoring/services/detector.py`
  安全帽检测封装。

- `src/helmet_monitoring/services/monitor.py`
  连续监控 worker，主要用于流媒体输入。

- `src/helmet_monitoring/ui/live_preview_stream.py`
  轻量实时预览服务，提供：
  - `/health`
  - `/browser/<camera_id>` 浏览器摄像头预览页
  - `/infer/<camera_id>` 浏览器帧推理接口
  - `/mjpeg/<camera_id>` MJPEG 预览接口

- `scripts/browser_camera_preview.py`
  启动轻量浏览器预览服务，并自动打开浏览器。

- `scripts/realtime_camera_viewer.py`
  基于 Tkinter + OpenCV 的本地桌面实时窗口。

- `scripts/run_monitor.py`
  监控 worker 入口。

- `docker-compose.yml`
  Docker 栈，包含 dashboard、RTMP 网关和 monitor。

### 仓库结构

```text
safety_helmet_yolo26/
├─ app.py                             # Streamlit 运维控制台入口
├─ docker-compose.yml                 # dashboard + monitor + RTMP 中继编排
├─ configs/
│  ├─ runtime.json                    # 当前生效的运行配置
│  └─ runtime.example.json            # 运行配置模板
├─ scripts/
│  ├─ start_desktop_webcam.cmd        # 浏览器本机摄像头演示启动器
│  ├─ start_realtime_webcam.cmd       # 本地桌面实时窗口启动器
│  ├─ start_stream_docker.cmd         # Docker 流媒体模式启动器
│  ├─ start_dashboard_service.cmd     # dashboard 托管服务启动器
│  ├─ start_monitor_service.cmd       # monitor 托管服务启动器
│  ├─ start_host_services.cmd         # 同时拉起两类托管服务
│  ├─ doctor.py                       # 环境与依赖诊断脚本
│  ├─ check_supabase.py               # Supabase 就绪检查脚本
│  ├─ smoke_product.py                # 端到端冒烟测试脚本
│  ├─ validate_notification_delivery.py # 独立通知链路验收脚本
│  ├─ bootstrap_identity_defaults.py  # 摄像头默认负责人建议/回填脚本
│  ├─ identity_delivery_audit.py      # 身份资料覆盖率审计脚本
│  ├─ dashboard_healthcheck.py        # dashboard 健康检查
│  ├─ monitor_healthcheck.py          # monitor worker 健康检查
│  └─ install_windows_autostart.ps1   # Windows 自启动计划任务安装脚本
├─ src/
│  └─ helmet_monitoring/              # 核心代码包（检测、监控、UI 服务）
├─ sql/                               # Supabase 建表与扩展 SQL
├─ tests/                             # 自动化测试
├─ artifacts/                         # 运行产物（抓拍、告警、训练、备份）
└─ docs/                              # 产品化与运维文档
```

### 运行环境

- 推荐 Python：`3.11`
- 兼容回退版本：`3.10`

创建虚拟环境并安装依赖：

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements.identity.txt
.venv\Scripts\python.exe -m pip install -r requirements.dev.txt
```

### 初始准备

初始化工作区：

```bash
.venv\Scripts\python.exe scripts/bootstrap_workspace.py --copy-env-example --copy-registry-example
```

运行环境检查：

```bash
.venv\Scripts\python.exe scripts/doctor.py --ensure-scaffold
```

如需更严格的部署检查：

```bash
.venv\Scripts\python.exe scripts/doctor.py --deploy-strict
```

### 环境变量配置

从 `configs/supabase.example.env` 复制生成 `.env`，再填入你自己的真实值。

重要变量包括：

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_STORAGE_BUCKET`
- `HELMET_CONFIG_PATH`
- `HELMET_PUBLISH_URL`
- `HELMET_MONITOR_STREAM_URL`
- `camera_use_laptop_camera=true`
- `HELMET_LIVE_PREVIEW_PORT`
- `OPENAI_API_KEY`
- `DEEPSEEK_API_KEY`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM_EMAIL`
- `ALERT_EMAIL_RECIPIENTS`
- `HELMET_AUTH_USERS_FILE`
- `HELMET_AUTH_ADMIN_USERNAME`
- `HELMET_AUTH_ADMIN_PASSWORD_HASH`

说明：

- `camera_use_laptop_camera=true` 会在加载配置时强制走本地摄像头演示模式。
- `HELMET_LIVE_PREVIEW_PORT` 默认是 `8876`。
- 不要把真实密钥提交到版本控制。
- 如果开发时有密钥泄露，正式部署前请先轮换。

### 运行配置说明

主配置文件是 `configs/runtime.json`。

重点字段：

- `model`
  - `path`：模型路径
  - `confidence`：检测阈值
  - `imgsz`：推理尺寸
  - `device`：设备，例如 `cpu`
  - `safe_labels`：视为安全的标签
  - `violation_labels`：视为违规的标签

- `monitoring`
  - `frame_stride`
  - `preview_fps`
  - `camera_retry_seconds`
  - `heartbeat_interval_seconds`
  - `max_frames`

- `cameras`
  - `camera_id`
  - `camera_name`
  - `source`
  - `enabled`

- `security`
  - `evidence_retention_days`
  - `signed_url_seconds`

当前和预览相关的行为：

- `monitoring.preview_fps` 默认是 `20.0`
- 安全目标画绿框
- 违规目标画红框

### 推荐启动方式

#### 1. 本地浏览器摄像头预览

如果你要的是“像视频一样尽量顺滑的本地实时预览”，优先使用这个模式。

启动方式：

```bash
start_desktop_webcam.cmd
```

它现在的行为是：

- 启动本地轻量预览服务
- 自动打开浏览器
- 浏览器直接读取摄像头
- 浏览器把帧发送到本地推理接口
- 页面上叠加红框 / 绿框

手动启动方式：

```bash
.venv\Scripts\python.exe scripts/browser_camera_preview.py
```

默认 URL 形式：

```text
http://127.0.0.1:8876/browser/<camera_id>
```

例如：

```text
http://127.0.0.1:8876/browser/cam-local-001
```

注意事项：

- 浏览器必须允许摄像头权限
- 建议使用 `localhost`、`127.0.0.1` 或 HTTPS
- 不能有别的软件长期占用摄像头

#### 2. 本地桌面实时窗口

如果你更希望直接打开一个本地桌面窗口，而不是网页，可以用这个模式。

启动方式：

```bash
start_realtime_webcam.cmd
```

手动启动方式：

```bash
.venv\Scripts\python.exe scripts/realtime_camera_viewer.py --source 0
```

常用调优示例：

```bash
.venv\Scripts\python.exe scripts/realtime_camera_viewer.py --source 0 --imgsz 256 --detect-interval-ms 100
.venv\Scripts\python.exe scripts/realtime_camera_viewer.py --source 0 --camera-width 1280 --camera-height 720
```

这个模式的特点：

- 后台线程持续读取最新帧
- 检测按固定间隔执行
- 短时间复用上一轮框结果来减轻卡顿感
- 绿框表示戴了安全帽
- 红框表示没戴安全帽

关闭方式：

- 直接关闭窗口
- 按 `Esc`
- 按 `q`

#### 3. Streamlit 运维控制台

如果你要做的是告警管理、人工复核、报表和配置管理，使用这个模式。

本地启动：

```bash
set YOLO_CONFIG_DIR=%CD%\.ultralytics
.venv\Scripts\streamlit.exe run app.py
```

默认地址：

```text
http://localhost:8501
```

适合的用途：

- 人工复核告警
- 查看摄像头状态
- 管理元数据
- 导出报表
- 查看通知日志

如果你的唯一目标是“本地摄像头尽量丝滑地看画面和框”，这个页面不是最佳入口，优先用前面的浏览器预览或桌面实时窗口。

#### 4. Docker 流媒体模式

这个模式适合以下输入源：

- RTSP 摄像头
- HTTP 视频流
- 手机 RTMP 推流

启动方式：

```bash
start_stream_docker.cmd
```

等价手动命令：

```bash
docker compose up -d --build
```

默认服务包括：

- `dashboard`
- `monitor`
- `rtmp-gateway`

如果需要 edge 反向代理：

```bash
docker compose --profile edge up -d --build
```

推荐 RTMP 路径：

1. 手机推流到 `HELMET_PUBLISH_URL`
2. Docker 内部中继地址是 `rtmp://rtmp-gateway:1935/live/stream`
3. `monitor` 读取 `HELMET_MONITOR_STREAM_URL`

### 数据库配置

在 Supabase SQL Editor 中按顺序执行以下 SQL：

1. `sql/supabase_phase1_schema.sql`
2. `sql/supabase_identity_extension.sql`
3. `sql/supabase_identity_delivery_extension.sql`
4. `sql/supabase_identity_ai_extension.sql`
5. `sql/supabase_product_extension.sql`

然后执行检查：

```bash
.venv\Scripts\python.exe scripts/check_supabase.py
```

理想输出包括：

- `identity_extension=ready`
- `identity_ai_extension=ready`
- `product_extension=ready`
- `storage_bucket_ready=true`

如果输出提示是本地后端或缺少凭据，说明系统仍处于本地 fallback 模式。

### 可选的人脸识别 / OCR 扩展

安装可选依赖：

```bash
.venv\Scripts\python.exe -m pip install -r requirements.identity.txt
```

注册本地人脸样本：

1. 把图片放到 `artifacts/identity/faces/<person_id>/`
2. 运行：

```bash
.venv\Scripts\python.exe scripts/register_face_profiles.py
```

同步人员台账：

```bash
.venv\Scripts\python.exe scripts/sync_person_registry.py
```

### 冒烟测试与校验

运行本地冒烟：

```bash
.venv\Scripts\python.exe scripts/smoke_product.py
```

运行带模型的冒烟：

```bash
.venv\Scripts\python.exe scripts/smoke_product.py --use-model
```

运行严格校验：

```bash
.venv\Scripts\python.exe scripts/smoke_product.py --strict-runtime --use-model --require-model-detection --final-status ignored
```

单独验证通知链路：

```bash
.venv\Scripts\python.exe scripts/validate_notification_delivery.py --mode dry_run
.venv\Scripts\python.exe scripts/validate_notification_delivery.py --mode smtp --require-success --recipient your@email.com
```

审计身份资料覆盖率和默认负责人准备度：

```bash
.venv\Scripts\python.exe scripts/identity_delivery_audit.py
.venv\Scripts\python.exe scripts/bootstrap_identity_defaults.py
```

运行测试：

```bash
.venv\Scripts\python.exe -m pytest -q
```

常用健康检查：

```bash
.venv\Scripts\python.exe scripts/dashboard_healthcheck.py
.venv\Scripts\python.exe scripts/monitor_healthcheck.py
.venv\Scripts\python.exe scripts/ops_status.py --json
```

本地托管服务启动：

```bash
start_dashboard_service.cmd
start_monitor_service.cmd
start_host_services.cmd
```

安装 / 卸载 Windows 自启动任务：

```bash
install_windows_autostart.cmd
uninstall_windows_autostart.cmd
```

现在安装器会优先尝试 Windows 计划任务；如果当前环境没有创建登录任务的权限，会自动降级为当前用户 Startup 启动项，不依赖 PowerShell。

### 当前产品能力

目前已经包含这些产品化能力：

- 多源视频输入
- 安全帽 / 未戴安全帽检测
- 目标跟踪与事件判定
- OCR 与人脸识别扩展
- 告警人工复核流程
- 截图和视频证据留存
- 摄像头管理
- 通知中心与日志
- 报表与导出
- Hard Case 采集与后续再训练

### 备份、恢复与发布

创建备份：

```bash
.venv\Scripts\python.exe scripts/backup_system.py --name ops-baseline
```

恢复备份：

```bash
.venv\Scripts\python.exe scripts/restore_system.py artifacts\backups\ops-baseline.zip
```

创建并激活发布快照：

```bash
.venv\Scripts\python.exe scripts/release_manager.py snapshot --name baseline-runtime --activate
```

回滚：

```bash
.venv\Scripts\python.exe scripts/release_manager.py rollback --steps 1
```

### 模型反馈闭环

导出在线反馈样本：

```bash
.venv\Scripts\python.exe scripts/model_feedback_loop.py export-feedback
```

构建合并数据集：

```bash
.venv\Scripts\python.exe scripts/model_feedback_loop.py build-dataset
```

注册并提升模型：

```bash
.venv\Scripts\python.exe scripts/model_feedback_loop.py register-model artifacts\training_runs\helmet_project\cpu_test3\weights\best.pt
.venv\Scripts\python.exe scripts/model_feedback_loop.py promote-model --model-path artifacts\training_runs\helmet_project\cpu_test3\weights\best.pt
```

执行完整闭环：

```bash
.venv\Scripts\python.exe scripts/model_feedback_loop.py full-cycle --train --promote
```

### 常见问题排查

#### 浏览器预览没有自动打开

- 手动打开终端里打印出来的 URL
- 默认端口通常是 `8876`
- 检查是否有其他进程占用了预览端口

#### 浏览器页面打开了，但没有摄像头画面

- 检查浏览器是否允许了摄像头权限
- 关闭其他占用摄像头的软件
- 确认配置里有启用的本地摄像头
- 如果你想强制本地摄像头模式，确认 `.env` 中设置了 `camera_use_laptop_camera=true`

#### `localhost:8501` 只显示空白页或骨架页

- 先等待 Streamlit 完整加载
- 如果你在用 Docker，可重建 dashboard：

```bash
docker compose up -d --build dashboard
```

- 如果你的目标是本地摄像头丝滑预览，不要把 `8501` 当成主要入口，优先使用 `start_desktop_webcam.cmd`

#### Docker 里读不到本机摄像头

这在 Windows 上很常见，推荐改用：

- 浏览器摄像头预览
- 本地桌面实时窗口
- RTSP / RTMP 推流模式

#### 画面还不够流畅

可以尝试：

- 使用浏览器摄像头预览，而不是 Streamlit 总览页
- 使用桌面实时窗口
- 降低 `imgsz`
- 增大 `detect-interval-ms`
- 关闭高 CPU 占用程序
- 如果有条件，改用 GPU 推理

### 更多参考文档

- `docs/industrialization_blueprint.md`
- `docs/productization_checklist.md`
- `docs/model_training_plan.md`
- `docs/keys_and_services_checklist.md`
