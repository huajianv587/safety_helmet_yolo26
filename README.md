# Safety Helmet Detection System

This repository has been upgraded from a Phase 1 MVP into a product-style operations console and monitoring worker.

## Python Standard

- Project default runtime: Python 3.11
- Supported fallback runtime: Python 3.10
- The local identity stack (face recognition + OCR) is validated on Python 3.11

Create or rebuild the project environment with Python 3.11:

```bash
C:\Users\Jhj\AppData\Local\Programs\Python\Python311\python.exe -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements.identity.txt
.venv\Scripts\python.exe -m pip install -r requirements.dev.txt
```

## Industrial Quick Start

1. Bootstrap folders and starter files:

```bash
.venv\Scripts\python.exe scripts/bootstrap_workspace.py --copy-env-example --copy-registry-example
```

2. Run a readiness inspection:

```bash
.venv\Scripts\python.exe scripts/doctor.py --ensure-scaffold
```

3. Verify database readiness:

```bash
.venv\Scripts\python.exe scripts/check_supabase.py
```

4. Run an end-to-end local smoke test without live cameras:

```bash
.venv\Scripts\python.exe scripts/smoke_product.py
```

5. Optional real-model smoke with the project virtual environment:

```bash
.venv\Scripts\python.exe scripts\smoke_product.py --use-model
```

6. Deployment-grade smoke that uses the configured backend/services and requires a real model hit:

```bash
.venv\Scripts\python.exe scripts\doctor.py --deploy-strict
.venv\Scripts\python.exe scripts\smoke_product.py --strict-runtime --use-model --require-model-detection --final-status ignored
```

## Current Product Scope

- Multi-source video input from webcam, RTSP, and local video files
- Cascade pipeline: person/no-helmet detection -> tracking -> event judgment -> OCR/face identity resolution
- Governance module for ignore zones, small-target filtering, night review, and whitelist cameras
- Alert workflow closure with `pending / confirmed / remediated / false_positive / ignored / assigned`
- Evidence chain with annotated snapshot, face crop, badge crop, and pre/post alert video clips
- Email notification center with per-camera recipients and notification logs
- Manual review desk for identity correction, assignment, remediation screenshots, and action history
- Camera management console with health metrics, hierarchy metadata, and runtime config updates
- Report center with trend charts, department ranking, person ranking, closure rate, and CSV export
- Hard-case collection for false positives and later YOLO26 hard-negative retraining
- Local fallback storage when Supabase product tables are not yet applied

## Project Layout

- `app.py`: Streamlit product console
- `scripts/run_monitor.py`: industrial monitoring worker entrypoint
- `scripts/bootstrap_workspace.py`: creates required folders and starter files
- `scripts/doctor.py`: readiness inspection for dependencies / keys / model / cameras
- `scripts/check_supabase.py`: checks schema readiness
- `scripts/smoke_product.py`: end-to-end local closure smoke test
- `scripts/train_yolo.py`: current YOLO training entrypoint
- `scripts/ops_status.py`: health, backup, release, and active-model summary
- `scripts/backup_system.py`: creates a recovery archive for configs / runtime / feedback assets
- `scripts/restore_system.py`: restores a backup archive into the current workspace
- `scripts/release_manager.py`: creates release snapshots and performs rollback
- `scripts/model_feedback_loop.py`: exports hard cases, builds merged datasets, registers models, and promotes versions
- `scripts/closed_loop_smoke.py`: injects synthetic alerts and validates the operational + model-feedback closed loop
- `scripts/dashboard_healthcheck.py`: dashboard health probe for Docker / schedulers
- `scripts/monitor_healthcheck.py`: monitor heartbeat health probe for Docker / schedulers
- `scripts/start_desktop_webcam.cmd`: starts the Docker dashboard and runs the monitor on the Windows host for laptop webcam mode
- `start_desktop_webcam.cmd`: root-level launcher for laptop webcam mode
- `start_stream_docker.cmd`: root-level launcher for RTSP / phone stream Docker mode
- `scripts/register_face_profiles.py`: syncs local employee face samples into `person_face_profiles`
- `scripts/enforce_retention.py`: dry-run/apply local evidence retention cleanup
- `configs/runtime.json`: active runtime configuration
- `configs/runtime.desktop.json`: formal desktop-webcam configuration for the Windows host monitor
- `configs/runtime.example.json`: reference industrial config
- `configs/supabase.example.env`: Supabase + SMTP environment template
- `requirements.identity.txt`: optional OCR / face recognition dependency bundle
- `sql/supabase_phase1_schema.sql`: base cameras + alerts schema
- `sql/supabase_identity_extension.sql`: employee master data + alert identity fields
- `sql/supabase_identity_ai_extension.sql`: OCR / face / LLM evidence fields
- `sql/supabase_product_extension.sql`: workflow, notification, hard case, audit, camera ops fields
- `docker-compose.yml`: dashboard + monitor services
- `deploy/caddy/Caddyfile`: HTTPS / reverse proxy entry for the optional edge profile
- `src/helmet_monitoring/`: main package

## Database Setup

Run the following SQL files in Supabase SQL Editor in order:

1. `sql/supabase_phase1_schema.sql`
2. `sql/supabase_identity_extension.sql`
3. `sql/supabase_identity_ai_extension.sql`
4. `sql/supabase_product_extension.sql`

Then verify:

```bash
.venv\Scripts\python.exe scripts/check_supabase.py
```

You want to see:

- `identity_extension=ready`
- `identity_ai_extension=ready`
- `product_extension=ready`
- `storage_bucket_ready=true`

If you see `backend=local` and `supabase_credentials=missing`, the system is still running in local fallback mode and the cloud closure is not yet connected.

## Environment Setup

Create `.env` from `configs/supabase.example.env`.

Important variables:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `HELMET_RTSP_URL`
- `OPENAI_API_KEY`
- `DEEPSEEK_API_KEY`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM_EMAIL`
- `ALERT_EMAIL_RECIPIENTS`

Detailed rollout references:

- `docs/industrialization_blueprint.md`
- `docs/productization_checklist.md`
- `docs/model_training_plan.md`
- `docs/keys_and_services_checklist.md`

## Run Locally

```bash
set YOLO_CONFIG_DIR=%CD%\.ultralytics
.venv\Scripts\python.exe scripts/run_monitor.py
```

Open the product console:

```bash
set YOLO_CONFIG_DIR=%CD%\.ultralytics
.venv\Scripts\streamlit.exe run app.py
```

## Optional Identity Stack

Install optional local OCR / face recognition packages:

```bash
.venv\Scripts\python.exe -m pip install -r requirements.identity.txt
```

Register employee face samples:

1. Put images into `artifacts/identity/faces/<person_id>/`
2. Run:

```bash
.venv\Scripts\python.exe scripts/register_face_profiles.py
```

Sync people registry into Supabase:

```bash
.venv\Scripts\python.exe scripts/sync_person_registry.py
```

Run the product smoke test:

```bash
.venv\Scripts\python.exe scripts/smoke_product.py
```

Run tests:

```bash
.venv\Scripts\python.exe -m pytest -q
```

## Docker Compose

```bash
docker compose up --build
```

Services:

- `dashboard`: Streamlit product console
- `monitor`: continuous monitoring worker for RTSP / HTTP / stream-based inputs
- `gateway` profile: optional Caddy reverse proxy with HTTPS termination
- Compose mounts `configs/`, `artifacts/`, `data/hard_cases/`, and `.ultralytics/` for persistence instead of bind-mounting the whole repo
- Product console URL: `http://localhost:8501`

Enable the edge proxy when you want HTTP/HTTPS entry in front of Streamlit:

```bash
docker compose --profile edge up -d --build
```

Useful health / ops commands:

```bash
.venv\Scripts\python.exe scripts\dashboard_healthcheck.py
.venv\Scripts\python.exe scripts\monitor_healthcheck.py
.venv\Scripts\python.exe scripts\ops_status.py --json
```

## Formal Startup Modes

### 1. Windows laptop webcam mode

Use this mode when you want to detect directly from the computer webcam.

```bash
start_desktop_webcam.cmd
```

What it does:

- Starts the `dashboard` in Docker
- Opens the web console at `http://localhost:8501`
- Runs the `monitor` on the Windows host with `configs/runtime.desktop.json`

Why this path exists:

- Docker Desktop on Windows runs the Python worker inside a Linux container
- The laptop webcam is usually not exposed to that container as `/dev/video0`
- So the official desktop-webcam mode is: dashboard in Docker, monitor on the host

### 2. RTSP / phone stream mode

Use this mode when the camera source is an RTSP / HTTP stream, including a phone camera app that publishes a stream URL.

1. Update the camera source in `configs/runtime.json`
2. Put your iPhone stream URL into `.env` as `HELMET_RTSP_URL=...`
3. Start the full stack:

```bash
start_stream_docker.cmd
```

Equivalent manual command:

```bash
docker compose up -d --build
```

In this mode, the Docker `monitor` service starts automatically and begins detection as soon as the configured stream is reachable.

## Product Pages

- `总览`: today metrics, trend, evidence wall, camera health
- `人工复核台`: alert detail, manual identity fix, assignment, remediation closure
- `摄像头管理`: hierarchy metadata, camera recipients, runtime config write-back
- `统计报表`: trends, closure rate, false positive rate, rankings, CSV export
- `通知中心`: email logs and test email
- `Hard Cases`: false-positive accumulation for retraining

## Evidence and Retention

- Snapshots, face crops, badge crops, clips, and remediation screenshots are stored under `artifacts/captures`
- Retention is controlled by `security.evidence_retention_days` in `configs/runtime.json`
- Dry run cleanup:

```bash
python scripts/enforce_retention.py
```

- Apply cleanup:

```bash
python scripts/enforce_retention.py --apply
```

## Backup, Release, Rollback

Create a baseline backup:

```bash
.venv\Scripts\python.exe scripts\backup_system.py --name ops-baseline
```

Restore a backup:

```bash
.venv\Scripts\python.exe scripts\restore_system.py artifacts\backups\ops-baseline.zip
```

Create and activate a release snapshot:

```bash
.venv\Scripts\python.exe scripts\release_manager.py snapshot --name baseline-runtime --activate
```

Rollback one release step:

```bash
.venv\Scripts\python.exe scripts\release_manager.py rollback --steps 1
```

## Model Feedback Loop

Export online hard cases into a training bundle:

```bash
.venv\Scripts\python.exe scripts\model_feedback_loop.py export-feedback
```

Build a merged dataset from the base corpus plus `data/hard_cases/labeled`:

```bash
.venv\Scripts\python.exe scripts\model_feedback_loop.py build-dataset
```

Register and promote a trained model:

```bash
.venv\Scripts\python.exe scripts\model_feedback_loop.py register-model artifacts\training_runs\helmet_project\cpu_test3\weights\best.pt
.venv\Scripts\python.exe scripts\model_feedback_loop.py promote-model --model-path artifacts\training_runs\helmet_project\cpu_test3\weights\best.pt
```

Run the closed-loop cycle with optional training:

```bash
.venv\Scripts\python.exe scripts\model_feedback_loop.py full-cycle --train --promote
```

Run a synthetic end-to-end closure smoke that covers:
- test alert injection
- assignment + remediation closure
- false-positive routing into hard cases
- feedback export and optional merged dataset build

```bash
.venv\Scripts\python.exe scripts\closed_loop_smoke.py --build-feedback-dataset
```

## Deployment Notes

- For production RTSP, prefer FFmpeg/GStreamer around the stream layer rather than relying only on bare OpenCV
- The current worker already supports a built-in tracker and Ultralytics ByteTrack mode
- Use private Supabase buckets plus signed URLs for formal deployments
- If you see a startup error that `/dev/video0` is unavailable inside Docker, switch to the Windows laptop webcam mode above or replace the source with RTSP / HTTP
- `scripts/smoke_product.py --strict-runtime --use-model --require-model-detection --final-status ignored` is intended for pre-release validation and may write smoke-test alerts/evidence to the configured backend
- Rotate any previously exposed `service_role` keys before production use
- Prefer the project `.venv` for training and model smoke tests because the system Python may not contain `ultralytics`
