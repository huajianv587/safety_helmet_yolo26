# Safety Helmet Detection System

This repository has been upgraded from a Phase 1 MVP into a product-style operations console and monitoring worker.

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
- `scripts/check_supabase.py`: checks schema readiness
- `scripts/register_face_profiles.py`: syncs local employee face samples into `person_face_profiles`
- `scripts/enforce_retention.py`: dry-run/apply local evidence retention cleanup
- `configs/runtime.json`: active runtime configuration
- `configs/runtime.example.json`: reference industrial config
- `configs/supabase.example.env`: Supabase + SMTP environment template
- `requirements.identity.txt`: optional OCR / face recognition dependency bundle
- `sql/supabase_phase1_schema.sql`: base cameras + alerts schema
- `sql/supabase_identity_extension.sql`: employee master data + alert identity fields
- `sql/supabase_identity_ai_extension.sql`: OCR / face / LLM evidence fields
- `sql/supabase_product_extension.sql`: workflow, notification, hard case, audit, camera ops fields
- `docker-compose.yml`: dashboard + monitor services
- `src/helmet_monitoring/`: main package

## Database Setup

Run the following SQL files in Supabase SQL Editor in order:

1. `sql/supabase_phase1_schema.sql`
2. `sql/supabase_identity_extension.sql`
3. `sql/supabase_identity_ai_extension.sql`
4. `sql/supabase_product_extension.sql`

Then verify:

```bash
python scripts/check_supabase.py
```

You want to see:

- `identity_extension=ready`
- `identity_ai_extension=ready`
- `product_extension=ready`
- `storage_bucket_ready=true`

## Environment Setup

Create `.env` from `configs/supabase.example.env`.

Important variables:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `OPENAI_API_KEY`
- `DEEPSEEK_API_KEY`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM_EMAIL`
- `ALERT_EMAIL_RECIPIENTS`

## Run Locally

```bash
set YOLO_CONFIG_DIR=%CD%\.ultralytics
python scripts/run_monitor.py
```

Open the product console:

```bash
set YOLO_CONFIG_DIR=%CD%\.ultralytics
streamlit run app.py
```

## Optional Identity Stack

Install optional local OCR / face recognition packages:

```bash
python -m pip install -r requirements.identity.txt
```

Register employee face samples:

1. Put images into `artifacts/identity/faces/<person_id>/`
2. Run:

```bash
python scripts/register_face_profiles.py
```

## Docker Compose

```bash
docker compose up --build
```

Services:

- `dashboard`: Streamlit product console
- `monitor`: continuous monitoring worker

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

## Deployment Notes

- For production RTSP, prefer FFmpeg/GStreamer around the stream layer rather than relying only on bare OpenCV
- The current worker already supports a built-in tracker and Ultralytics ByteTrack mode
- Use private Supabase buckets plus signed URLs for formal deployments
- Rotate any previously exposed `service_role` keys before production use
