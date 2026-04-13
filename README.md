# Safety Helmet Monitoring System

## English Version

### 1. What This Project Is

This repository is a product-style safety helmet monitoring system built around:

- a YOLO-based detection pipeline
- a continuous monitoring worker
- a Streamlit operations console
- Supabase-backed alert storage and workflow management
- optional identity resolution with badge OCR, face recognition, and LLM fallback

This is not just a model demo. It is a full workflow system for:

- detecting no-helmet violations
- generating alerts with snapshots and clips
- resolving worker identity
- notifying responsible people
- reviewing and closing cases
- collecting hard cases for future model improvement
- operating the system with health checks, backups, release snapshots, and service supervision

Current visual convention:

- green box = safe / helmet detected
- red box = violation / no helmet detected

### 2. Runtime Modes

The project supports three main runtime paths:

1. Browser-based local webcam preview
   Recommended when you want a smooth local demo without opening the full dashboard first.

2. Desktop real-time viewer
   Recommended when you want a native local preview window based on Tkinter + OpenCV.

3. Managed dashboard + monitor services
   Recommended for regular host-based usage on Windows.

Docker is supported, but it is optional. If you are not preparing Docker deployment right now, you can ignore the Docker-related sections and use the host-based scripts only.

### 3. Main Components

- `app.py`
  Main Streamlit product console.

- `src/helmet_monitoring/core/config.py`
  Central configuration loader. Merges `.env` and `configs/runtime*.json` into one `AppSettings` object.

- `src/helmet_monitoring/services/monitor.py`
  Main backend orchestrator. Reads camera frames, runs detection, applies governance, resolves identity, writes evidence, creates alerts, and sends notifications.

- `src/helmet_monitoring/services/detector.py`
  Ultralytics YOLO wrapper for detection and optional tracking.

- `src/helmet_monitoring/services/event_engine.py`
  Converts frame-level detections into event-level alerts.

- `src/helmet_monitoring/services/identity_resolver.py`
  Cascades badge OCR, face recognition, LLM fallback, and camera default identity rules.

- `src/helmet_monitoring/storage/repository.py`
  Storage abstraction with Supabase-first behavior and local JSON/JSONL fallback.

- `src/helmet_monitoring/storage/evidence_store.py`
  Saves snapshots and clips locally and optionally uploads them to Supabase Storage.

- `src/helmet_monitoring/ui/live_preview_stream.py`
  Lightweight preview server exposing:
  - `/health`
  - `/browser/<camera_id>`
  - `/infer/<camera_id>`
  - `/mjpeg/<camera_id>`

### 4. Architecture Overview

High-level processing flow:

1. `load_settings()` loads runtime configuration.
2. `CameraStream` opens webcam or remote stream sources.
3. `HelmetDetector` runs YOLO inference.
4. `ViolationEventEngine` groups repeated violation detections into alert candidates.
5. `FalsePositiveGovernance` filters small targets, ignore zones, whitelist cameras, and low-confidence/night cases.
6. `IdentityResolver` tries badge OCR, face recognition, LLM fallback, and camera-default person binding.
7. `EvidenceStore` writes snapshots and clips.
8. `AlertRepository` persists alerts, actions, notifications, hard cases, and audit logs.
9. `NotificationService` sends or simulates email notifications.
10. `AlertWorkflowService` handles assignment, remediation, false-positive closure, and hard-case sinking.

### 5. Repository Layout

```text
safety_helmet_yolo26/
├─ app.py
├─ Dockerfile
├─ docker-compose.yml
├─ requirements.txt
├─ requirements.identity.txt
├─ requirements.dev.txt
├─ configs/
│  ├─ runtime.json
│  ├─ runtime.example.json
│  ├─ runtime.desktop.json
│  ├─ runtime.quicktest.json
│  ├─ person_registry.json
│  ├─ person_registry.example.json
│  ├─ supabase.example.env
│  └─ datasets/
├─ deploy/
│  └─ caddy/
├─ sql/
├─ src/
│  └─ helmet_monitoring/
│     ├─ core/
│     ├─ services/
│     ├─ storage/
│     ├─ ui/
│     └─ utils/
├─ scripts/
├─ tests/
├─ data/
├─ artifacts/
├─ docs/
└─ legacy/
```

#### Key folders

- `configs/`
  Runtime config, person registry, dataset YAML, env template.

- `deploy/`
  Reverse proxy configuration for the optional edge deployment path.

- `sql/`
  Supabase schema and extension scripts.

- `src/helmet_monitoring/`
  Real application code.

- `scripts/`
  Operational helpers, smoke tests, health checks, training tools, release tools, startup wrappers.

- `tests/`
  Pytest suite covering config, monitoring, workflow, governance, repository, preview, and operations modules.

- `data/`
  Local dataset and hard-case feedback assets.

- `artifacts/`
  Runtime outputs, captures, clips, models, releases, backups, exports, service logs, and training runs.

### 6. Tech Stack

#### Vision and ML

- Ultralytics YOLO
- OpenCV
- NumPy
- Pillow

#### UI and analytics

- Streamlit
- Altair
- Pandas

#### Identity stack

- PaddleOCR
- RapidOCR
- facenet-pytorch
- torch

#### Platform and integration

- Supabase Database
- Supabase Storage
- httpx
- python-dotenv
- smtplib

#### Operations and deployment

- Docker
- docker-compose
- Caddy
- nginx-rtmp
- pytest
- GitHub Actions

### 7. Supported Python Version

- recommended: Python `3.11`
- supported fallback: Python `3.10`

The repository currently uses Python 3.11 in local CI and in the provided Dockerfile.

The repository now includes a tracked default checkpoint at `models/best.pt`, so a fresh machine does not need a separate manual model copy.

### 8. Installation

Create a virtual environment:

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements.identity.txt
.venv\Scripts\python.exe -m pip install -r requirements.dev.txt
```

### 9. First-Time Setup

Bootstrap the workspace:

```bash
.venv\Scripts\python.exe scripts\bootstrap_workspace.py --copy-env-example --copy-registry-example
```

Run readiness inspection:

```bash
.venv\Scripts\python.exe scripts\doctor.py --ensure-scaffold
```

Strict deployment inspection:

```bash
.venv\Scripts\python.exe scripts\doctor.py --deploy-strict
```

#### Fresh Windows Machine Checklist

If you want a new Windows machine to behave almost the same as the current host setup, use this order:

```bash
git clone <repo-url>
cd safety_helmet_yolo26

# copy the same .env file into the repository root

python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install -r requirements.identity.txt
.venv\Scripts\python.exe scripts\bootstrap_workspace.py --copy-registry-example
.venv\Scripts\python.exe scripts\doctor.py --ensure-scaffold
.venv\Scripts\python.exe scripts\doctor.py --deploy-strict
```

Then run:

```bash
start_host_services.cmd
```

Notes:

- `models/best.pt` is tracked in the repository, so you do not need to copy the model separately.
- If you reuse the same `.env`, the new machine can continue using the same Supabase project and service credentials.
- Keep `camera_use_laptop_camera=true` in `.env` if the new machine should use its own webcam.
- The new machine still needs Python installed, a usable camera, and camera permission at the OS level.

### 10. Environment Variables

Create `.env` from `configs/supabase.example.env` and fill in the required values.

Important keys:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_STORAGE_BUCKET`
- `HELMET_STORAGE_BACKEND`
- `HELMET_CONFIG_PATH`
- `HELMET_MONITOR_STREAM_URL`
- `HELMET_PUBLISH_URL`
- `HELMET_LIVE_PREVIEW_PORT`
- `camera_use_laptop_camera=true`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM_EMAIL`
- `SMTP_USE_TLS`
- `ALERT_EMAIL_RECIPIENTS`
- `OPENAI_API_KEY`
- `DEEPSEEK_API_KEY`
- `HELMET_AUTH_ADMIN_USERNAME`
- `HELMET_AUTH_ADMIN_PASSWORD_HASH`
- `HELMET_AUTH_ADMIN_DISPLAY_NAME`
- `HELMET_AUTH_ADMIN_ROLE`

Notes:

- `camera_use_laptop_camera=true` forces local-camera demo selection during settings loading.
- If you want RTSP/RTMP/HTTP remote stream monitoring, turn that flag off and configure remote stream sources instead.
- Do not commit real secrets.

### 11. Runtime Configuration

Main file:

```text
configs/runtime.json
```

Important sections:

- `repository_backend`
  Usually `supabase` or `local`.

- `model`
  - `path`
  - `confidence`
  - `imgsz`
  - `device`
  - `violation_labels`
  - `safe_labels`

- `event_rules`
  - `alert_frames`
  - `dedupe_seconds`
  - `match_distance_pixels`
  - `max_track_age_seconds`
  - `min_confidence_for_alert`

- `monitoring`
  - `frame_stride`
  - `preview_fps`
  - `camera_retry_seconds`
  - `heartbeat_interval_seconds`
  - `max_frames`

- `identity`
  - `provider`
  - `registry_path`
  - `refresh_seconds`

- `face_recognition`
  - `enabled`
  - `provider`
  - `device`
  - `similarity_threshold`
  - `review_threshold`
  - `face_profile_dir`

- `ocr`
  - `enabled`
  - `provider`
  - `min_confidence`

- `llm_fallback`
  - `enabled`
  - `use_openai`
  - `use_deepseek`
  - `openai_model`
  - `deepseek_model`

- `governance`
  - `enabled`
  - `min_bbox_area`
  - `ignore_zones`
  - `whitelist_camera_ids`
  - `night_confidence_boost`
  - `review_confidence_margin`

- `clip`
  - `enabled`
  - `pre_seconds`
  - `post_seconds`
  - `fps`
  - `codec`

- `notifications`
  - `enabled`
  - `email_enabled`
  - `default_recipients`

- `security`
  - `use_private_bucket`
  - `signed_url_seconds`
  - `evidence_retention_days`
  - `audit_enabled`

- `cameras`
  - `camera_id`
  - `camera_name`
  - `source`
  - `enabled`
  - `location`
  - `department`
  - hierarchy fields such as `site_name`, `building_name`, `floor_name`, `workshop_name`, `zone_name`

### 12. Supabase SQL Setup

Run these SQL files in order:

1. `sql/supabase_phase1_schema.sql`
2. `sql/supabase_identity_extension.sql`
3. `sql/supabase_identity_ai_extension.sql`
4. `sql/supabase_identity_delivery_extension.sql`
5. `sql/supabase_product_extension.sql`

This order matters because later scripts extend tables created in earlier phases.

### 13. Identity Data Preparation

#### Person registry

Example and active registry:

- `configs/person_registry.example.json`
- `configs/person_registry.json`

Generate demo people if needed:

```bash
.venv\Scripts\python.exe scripts\generate_demo_persons.py
```

#### Sync registry to Supabase

```bash
.venv\Scripts\python.exe scripts\sync_person_registry.py
```

#### Suggest or apply camera default people

```bash
.venv\Scripts\python.exe scripts\bootstrap_identity_defaults.py
.venv\Scripts\python.exe scripts\bootstrap_identity_defaults.py --apply
```

#### Register face profiles

Put local face samples under:

```text
artifacts/identity/faces/<person_id>/
```

Then run:

```bash
.venv\Scripts\python.exe scripts\register_face_profiles.py
```

#### Audit identity delivery readiness

```bash
.venv\Scripts\python.exe scripts\identity_delivery_audit.py
```

### 14. Recommended Non-Docker Startup Modes

#### A. Browser local webcam preview

Recommended for simple local demos.

Launch:

```bash
start_desktop_webcam.cmd
```

Important note:

Despite its name, this script starts the browser preview path, not the native desktop viewer.

Direct Python launch:

```bash
.venv\Scripts\python.exe scripts\browser_camera_preview.py
```

#### B. Native desktop real-time viewer

Launch:

```bash
start_realtime_webcam.cmd
```

Direct Python launch:

```bash
.venv\Scripts\python.exe scripts\realtime_camera_viewer.py --source 0
```

#### C. Managed dashboard + monitor services on the host

Launch both:

```bash
start_host_services.cmd
```

Launch dashboard only:

```bash
start_dashboard_service.cmd
```

Launch monitor only:

```bash
start_monitor_service.cmd
```

These managed services use health checks and automatic restart supervision.

### 15. Optional Docker Startup Mode

Use Docker only if you want containerized stream monitoring.

Launch:

```bash
start_stream_docker.cmd
```

This script validates:

- `HELMET_MONITOR_STREAM_URL`
- `HELMET_PUBLISH_URL` when RTMP relay mode is used

Then it runs:

```bash
docker compose up -d --build
```

Important limitations:

- Docker Desktop on Windows/macOS is not ideal for direct laptop webcam access inside the container.
- For local laptop webcam mode, host-based scripts are recommended.

### 16. Validation and Smoke Tests

#### Readiness

```bash
.venv\Scripts\python.exe scripts\doctor.py --json
.venv\Scripts\python.exe scripts\doctor.py --deploy-strict
```

#### Supabase

```bash
.venv\Scripts\python.exe scripts\check_supabase.py
.venv\Scripts\python.exe scripts\ensure_storage_bucket.py
```

#### Storage and notification delivery

```bash
.venv\Scripts\python.exe scripts\validate_storage_delivery.py --require-success
.venv\Scripts\python.exe scripts\validate_notification_delivery.py --mode auto
```

#### Face profile validation

```bash
.venv\Scripts\python.exe scripts\validate_face_profiles.py --person-ids person-001,person-002
```

#### Model validation

```bash
.venv\Scripts\python.exe scripts\validate_yolo.py --data configs/datasets/shwd_yolo26.yaml
```

#### Product smoke tests

```bash
.venv\Scripts\python.exe scripts\smoke_product.py
.venv\Scripts\python.exe scripts\trigger_test_alert.py --person-id person-001
.venv\Scripts\python.exe scripts\closed_loop_smoke.py --build-feedback-dataset
```

#### Test suite

```bash
.venv\Scripts\python.exe -m pytest -q
```

### 17. Training and Model Lifecycle

#### Train

```bash
.venv\Scripts\python.exe scripts\train_yolo.py --data configs/datasets/shwd_yolo26.yaml --name train_product
```

#### Validate

```bash
.venv\Scripts\python.exe scripts\validate_yolo.py --data configs/datasets/shwd_yolo26.yaml --weights <model_path>
```

#### Import the Voxel hard-hat dataset

```bash
.venv\Scripts\python.exe scripts\import_voxel_hardhat.py
```

#### Feedback loop

```bash
.venv\Scripts\python.exe scripts\model_feedback_loop.py export-feedback
.venv\Scripts\python.exe scripts\model_feedback_loop.py build-dataset
.venv\Scripts\python.exe scripts\model_feedback_loop.py full-cycle --train --promote
```

### 18. Operations and Release Management

#### Service health and status

```bash
.venv\Scripts\python.exe scripts\ops_status.py
.venv\Scripts\python.exe scripts\monitor_healthcheck.py
.venv\Scripts\python.exe scripts\dashboard_healthcheck.py
```

#### Backups

```bash
.venv\Scripts\python.exe scripts\backup_system.py --name ops-baseline
.venv\Scripts\python.exe scripts\restore_system.py <backup_zip>
```

#### Release snapshots

```bash
.venv\Scripts\python.exe scripts\release_manager.py snapshot --name my-release --activate
.venv\Scripts\python.exe scripts\release_manager.py status
.venv\Scripts\python.exe scripts\release_manager.py rollback --steps 1
```

#### Windows autostart

```bash
install_windows_autostart.cmd
uninstall_windows_autostart.cmd
```

### 19. Security Notes

- Prefer `security.use_private_bucket=true`.
- Prefer signed URLs over public evidence URLs.
- Keep camera credentials out of tracked config files.
- Keep `.env` local and rotate any exposed secrets.
- Use trusted console authentication (`HELMET_AUTH_ADMIN_*` or managed auth users file).

### 20. Troubleshooting

#### No local webcam appears

- make sure `camera_use_laptop_camera=true` if you want local-camera demo behavior
- close other applications that may hold the webcam
- use host mode instead of Docker for local webcam access

#### Dashboard works but monitor does not

- check `scripts\start_monitor_service.cmd`
- inspect `artifacts\runtime\services\monitor_service.log`
- run `scripts\doctor.py --deploy-strict`

#### Supabase falls back to local storage

- verify `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`
- run all SQL extensions in order
- run `scripts\check_supabase.py`

#### Notifications are skipped

- check SMTP variables in `.env`
- run `scripts\validate_notification_delivery.py`

#### Face recognition or OCR is unavailable

- install `requirements.identity.txt`
- verify local face samples and person registry quality

---

## 中文版本

### 1. 项目定位

这个仓库是一个“产品化的安全帽监测系统”，核心不是单一模型 Demo，而是一整套从检测到闭环处置的工作流系统，包含：

- 基于 YOLO 的违规检测
- 持续运行的监控 worker
- Streamlit 运维控制台
- Supabase 告警与流程数据面
- 可选的身份解析能力（工牌 OCR、人脸识别、LLM 回退）

系统可以完成：

- 未戴安全帽违规检测
- 自动生成告警、快照、短视频证据
- 识别人员身份
- 发送通知
- 人工复核与结案
- 误报 / 漏报案例回流
- 服务健康检查、备份、发布快照和运维管理

当前画面语义：

- 绿色框 = 安全 / 检测到安全帽
- 红色框 = 违规 / 未戴安全帽

### 2. 运行模式

目前支持三条主运行路径：

1. 本机浏览器摄像头预览
   适合轻量演示，不需要先启动完整控制台。

2. 本机桌面原生实时预览
   适合用 Tkinter + OpenCV 弹出本地窗口做低延迟观察。

3. 主机受管服务模式
   适合 Windows 主机上稳定跑 dashboard + monitor。

Docker 是可选项，不是必选项。如果你当前不打算做 Docker 部署，可以先完全忽略 Docker 相关章节，只使用主机脚本即可。

### 3. 核心组件

- `app.py`
  主 Streamlit 产品控制台。

- `src/helmet_monitoring/core/config.py`
  全局配置中心，负责把 `.env` 和 `configs/runtime*.json` 合并成 `AppSettings`。

- `src/helmet_monitoring/services/monitor.py`
  最核心的后端编排器：读帧、检测、治理、身份解析、存证、告警入库、通知发送。

- `src/helmet_monitoring/services/detector.py`
  YOLO 检测封装，支持普通检测和可选跟踪。

- `src/helmet_monitoring/services/event_engine.py`
  把逐帧检测聚合为事件级告警。

- `src/helmet_monitoring/services/identity_resolver.py`
  级联身份解析：工牌 OCR、人脸识别、LLM 回退、摄像头默认人员规则。

- `src/helmet_monitoring/storage/repository.py`
  存储抽象层，优先 Supabase，异常时可回退到本地 JSON/JSONL。

- `src/helmet_monitoring/storage/evidence_store.py`
  本地保存证据，同时可选上传到 Supabase Storage。

- `src/helmet_monitoring/ui/live_preview_stream.py`
  轻量预览服务，暴露：
  - `/health`
  - `/browser/<camera_id>`
  - `/infer/<camera_id>`
  - `/mjpeg/<camera_id>`

### 4. 整体架构

高层处理流程如下：

1. `load_settings()` 加载配置。
2. `CameraStream` 打开摄像头或远程流。
3. `HelmetDetector` 做 YOLO 推理。
4. `ViolationEventEngine` 把连续违规框聚合成候选告警。
5. `FalsePositiveGovernance` 做误报治理和人工复核标记。
6. `IdentityResolver` 尝试 OCR / 人脸 / LLM / 默认绑定。
7. `EvidenceStore` 写入快照和 clip。
8. `AlertRepository` 落库告警、动作、通知、hard case、审计日志。
9. `NotificationService` 发送或模拟通知。
10. `AlertWorkflowService` 执行派单、整改、误报关闭与样本回流。

### 5. 仓库结构

```text
safety_helmet_yolo26/
├─ app.py
├─ Dockerfile
├─ docker-compose.yml
├─ requirements.txt
├─ requirements.identity.txt
├─ requirements.dev.txt
├─ configs/
├─ deploy/
├─ sql/
├─ src/
├─ scripts/
├─ tests/
├─ data/
├─ artifacts/
├─ docs/
└─ legacy/
```

#### 关键目录说明

- `configs/`
  运行时配置、人员注册表、数据集 YAML、环境变量模板。

- `deploy/`
  可选边缘代理部署配置。

- `sql/`
  Supabase 建表与扩表脚本。

- `src/helmet_monitoring/`
  真实业务代码主体。

- `scripts/`
  启动脚本、健康检查、烟雾测试、训练、发布、备份等运维辅助脚本。

- `tests/`
  pytest 自动化测试。

- `data/`
  数据集和 hard case 标注反馈数据。

- `artifacts/`
  运行产物、快照、模型、导出、服务日志、备份、发布快照。

### 6. 技术栈

#### 视觉与模型

- Ultralytics YOLO
- OpenCV
- NumPy
- Pillow

#### 界面与分析

- Streamlit
- Altair
- Pandas

#### 身份解析

- PaddleOCR
- RapidOCR
- facenet-pytorch
- torch

#### 平台集成

- Supabase Database
- Supabase Storage
- httpx
- python-dotenv
- smtplib

#### 运维与部署

- Docker
- docker-compose
- Caddy
- nginx-rtmp
- pytest
- GitHub Actions

### 7. Python 版本要求

- 推荐：Python `3.11`
- 兼容：Python `3.10`

当前仓库本地和 Dockerfile 默认都使用 Python 3.11。

仓库现在已经自带一个可跟踪的默认模型 `models/best.pt`，新电脑不需要再额外手动拷贝模型文件。

### 8. 安装方式

创建虚拟环境：

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements.identity.txt
.venv\Scripts\python.exe -m pip install -r requirements.dev.txt
```

### 9. 首次初始化

补齐目录与示例文件：

```bash
.venv\Scripts\python.exe scripts\bootstrap_workspace.py --copy-env-example --copy-registry-example
```

执行 readiness 检查：

```bash
.venv\Scripts\python.exe scripts\doctor.py --ensure-scaffold
```

执行严格部署检查：

```bash
.venv\Scripts\python.exe scripts\doctor.py --deploy-strict
```

#### 新电脑迁移清单

如果你想让一台新的 Windows 电脑尽量复现当前这台机器的主机模式效果，建议按下面顺序执行：

```bash
git clone <仓库地址>
cd safety_helmet_yolo26

# 把同一份 .env 复制到仓库根目录

python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install -r requirements.identity.txt
.venv\Scripts\python.exe scripts\bootstrap_workspace.py --copy-registry-example
.venv\Scripts\python.exe scripts\doctor.py --ensure-scaffold
.venv\Scripts\python.exe scripts\doctor.py --deploy-strict
```

然后执行：

```bash
start_host_services.cmd
```

说明：

- `models/best.pt` 已经纳入仓库，不需要再单独拷贝模型。
- 如果你复制的是同一份 `.env`，新机器就可以继续连接同一个 Supabase 项目和同一组服务凭据。
- 如果新机器要使用它自己的本机摄像头，请在 `.env` 里保留 `camera_use_laptop_camera=true`。
- 新机器仍然需要本机已安装 Python、有可用摄像头，并且系统层面允许摄像头访问。

### 10. 环境变量

建议以 `configs/supabase.example.env` 为模板创建 `.env`。

关键变量包括：

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_STORAGE_BUCKET`
- `HELMET_STORAGE_BACKEND`
- `HELMET_CONFIG_PATH`
- `HELMET_MONITOR_STREAM_URL`
- `HELMET_PUBLISH_URL`
- `HELMET_LIVE_PREVIEW_PORT`
- `camera_use_laptop_camera=true`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM_EMAIL`
- `SMTP_USE_TLS`
- `ALERT_EMAIL_RECIPIENTS`
- `OPENAI_API_KEY`
- `DEEPSEEK_API_KEY`
- `HELMET_AUTH_ADMIN_USERNAME`
- `HELMET_AUTH_ADMIN_PASSWORD_HASH`
- `HELMET_AUTH_ADMIN_DISPLAY_NAME`
- `HELMET_AUTH_ADMIN_ROLE`

说明：

- 如果你想优先演示本机笔记本摄像头，保留 `camera_use_laptop_camera=true`。
- 如果你想跑 RTSP / RTMP / HTTP 远程流，关闭这个开关并配置远程流地址。
- 不要提交真实密钥。

### 11. 运行时配置

主配置文件：

```text
configs/runtime.json
```

重要配置段：

- `repository_backend`
- `model`
- `event_rules`
- `monitoring`
- `identity`
- `face_recognition`
- `ocr`
- `llm_fallback`
- `governance`
- `clip`
- `notifications`
- `security`
- `cameras`

### 12. Supabase SQL 初始化顺序

请按下面顺序执行：

1. `sql/supabase_phase1_schema.sql`
2. `sql/supabase_identity_extension.sql`
3. `sql/supabase_identity_ai_extension.sql`
4. `sql/supabase_identity_delivery_extension.sql`
5. `sql/supabase_product_extension.sql`

后面的脚本依赖前面已经创建好的表和字段，所以顺序不能乱。

### 13. 身份数据准备

#### 人员注册表

相关文件：

- `configs/person_registry.example.json`
- `configs/person_registry.json`

如需生成演示人员：

```bash
.venv\Scripts\python.exe scripts\generate_demo_persons.py
```

#### 同步到 Supabase

```bash
.venv\Scripts\python.exe scripts\sync_person_registry.py
```

#### 自动建议摄像头默认人员

```bash
.venv\Scripts\python.exe scripts\bootstrap_identity_defaults.py
.venv\Scripts\python.exe scripts\bootstrap_identity_defaults.py --apply
```

#### 注册人脸特征

把人脸样本放到：

```text
artifacts/identity/faces/<person_id>/
```

然后执行：

```bash
.venv\Scripts\python.exe scripts\register_face_profiles.py
```

#### 审计身份覆盖率

```bash
.venv\Scripts\python.exe scripts\identity_delivery_audit.py
```

### 14. 推荐的非 Docker 启动方式

#### A. 浏览器本机摄像头预览

适合本机轻量演示。

启动：

```bash
start_desktop_webcam.cmd
```

重要说明：

这个脚本名字里虽然有 “desktop”，但它实际启动的是浏览器预览路径，不是原生桌面 viewer。

Python 直接启动：

```bash
.venv\Scripts\python.exe scripts\browser_camera_preview.py
```

#### B. 原生桌面实时预览

启动：

```bash
start_realtime_webcam.cmd
```

Python 直接启动：

```bash
.venv\Scripts\python.exe scripts\realtime_camera_viewer.py --source 0
```

#### C. 主机受管服务模式

同时启动 dashboard + monitor：

```bash
start_host_services.cmd
```

只启动 dashboard：

```bash
start_dashboard_service.cmd
```

只启动 monitor：

```bash
start_monitor_service.cmd
```

这些受管服务带有健康检查和自动重启能力。

### 15. 可选的 Docker 启动方式

如果你需要容器化流媒体监控，可以使用：

```bash
start_stream_docker.cmd
```

它会先检查：

- `HELMET_MONITOR_STREAM_URL`
- 如果走 RTMP relay，还会检查 `HELMET_PUBLISH_URL`

然后执行：

```bash
docker compose up -d --build
```

注意：

- Windows / macOS 下的 Docker Desktop 不适合直接读取本机笔记本摄像头。
- 本机笔记本摄像头模式优先建议走主机脚本，而不是容器。

### 16. 验证与烟雾测试

#### readiness

```bash
.venv\Scripts\python.exe scripts\doctor.py --json
.venv\Scripts\python.exe scripts\doctor.py --deploy-strict
```

#### Supabase

```bash
.venv\Scripts\python.exe scripts\check_supabase.py
.venv\Scripts\python.exe scripts\ensure_storage_bucket.py
```

#### 存储和通知链路

```bash
.venv\Scripts\python.exe scripts\validate_storage_delivery.py --require-success
.venv\Scripts\python.exe scripts\validate_notification_delivery.py --mode auto
```

#### 人脸 profile 验证

```bash
.venv\Scripts\python.exe scripts\validate_face_profiles.py --person-ids person-001,person-002
```

#### 模型验证

```bash
.venv\Scripts\python.exe scripts\validate_yolo.py --data configs/datasets/shwd_yolo26.yaml
```

#### 产品级烟雾测试

```bash
.venv\Scripts\python.exe scripts\smoke_product.py
.venv\Scripts\python.exe scripts\trigger_test_alert.py --person-id person-001
.venv\Scripts\python.exe scripts\closed_loop_smoke.py --build-feedback-dataset
```

#### 单元测试

```bash
.venv\Scripts\python.exe -m pytest -q
```

### 17. 训练与模型治理

#### 训练

```bash
.venv\Scripts\python.exe scripts\train_yolo.py --data configs/datasets/shwd_yolo26.yaml --name train_product
```

#### 验证

```bash
.venv\Scripts\python.exe scripts\validate_yolo.py --data configs/datasets/shwd_yolo26.yaml --weights <model_path>
```

#### 导入 Voxel 硬帽数据集

```bash
.venv\Scripts\python.exe scripts\import_voxel_hardhat.py
```

#### 模型反馈闭环

```bash
.venv\Scripts\python.exe scripts\model_feedback_loop.py export-feedback
.venv\Scripts\python.exe scripts\model_feedback_loop.py build-dataset
.venv\Scripts\python.exe scripts\model_feedback_loop.py full-cycle --train --promote
```

### 18. 运维与发布管理

#### 服务状态

```bash
.venv\Scripts\python.exe scripts\ops_status.py
.venv\Scripts\python.exe scripts\monitor_healthcheck.py
.venv\Scripts\python.exe scripts\dashboard_healthcheck.py
```

#### 备份

```bash
.venv\Scripts\python.exe scripts\backup_system.py --name ops-baseline
.venv\Scripts\python.exe scripts\restore_system.py <backup_zip>
```

#### 发布快照

```bash
.venv\Scripts\python.exe scripts\release_manager.py snapshot --name my-release --activate
.venv\Scripts\python.exe scripts\release_manager.py status
.venv\Scripts\python.exe scripts\release_manager.py rollback --steps 1
```

#### Windows 自启动

```bash
install_windows_autostart.cmd
uninstall_windows_autostart.cmd
```

### 19. 安全建议

- 建议 `security.use_private_bucket=true`
- 建议使用 signed URL，不要公开证据地址
- 不要把摄像头敏感凭据写进受版本管理的配置文件
- `.env` 只保留在本地，暴露过的密钥要及时轮换
- 启用可信控制台登录（`HELMET_AUTH_ADMIN_*` 或受管账号文件）

### 20. 常见问题

#### 本机摄像头打不开

- 如果要演示本机摄像头，确认 `camera_use_laptop_camera=true`
- 关闭可能占用摄像头的其他程序
- 本机摄像头优先使用主机模式，不建议用 Docker

#### dashboard 正常但 monitor 不工作

- 检查 `scripts\start_monitor_service.cmd`
- 查看 `artifacts\runtime\services\monitor_service.log`
- 执行 `scripts\doctor.py --deploy-strict`

#### Supabase 自动回退到本地存储

- 检查 `SUPABASE_URL` 和 `SUPABASE_SERVICE_ROLE_KEY`
- 确认 SQL 已按顺序执行
- 执行 `scripts\check_supabase.py`

#### 通知被跳过

- 检查 `.env` 里的 SMTP 配置
- 执行 `scripts\validate_notification_delivery.py`

#### OCR / 人脸识别不可用

- 安装 `requirements.identity.txt`
- 检查人脸样本和人员注册表质量
