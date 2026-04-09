# Keys And Services Checklist

## 1. Required for full industrial closure

### Supabase

You need:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

Purpose:

- alerts table storage
- camera table storage
- persons / face profiles
- workflow logs
- hard cases
- audit logs
- evidence storage bucket

### SMTP mail service

You need:

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM_EMAIL`

Recommended:

- `ALERT_EMAIL_RECIPIENTS`

Purpose:

- real alert notification
- notification closure verification

### LLM fallback

At least one of the following is recommended:

- `OPENAI_API_KEY`
- `DEEPSEEK_API_KEY`

Purpose:

- resolve ambiguous badge OCR text
- reduce manual identity workload

## 2. Optional but strongly recommended services

- GPU or strong inference machine
- RTSP-capable camera or sample MP4 source
- phone RTMP push app plus a fixed relay target such as `HELMET_PUBLISH_URL -> HELMET_MONITOR_STREAM_URL`
- annotation workflow such as CVAT / Label Studio / Roboflow

## 3. What you need to provide manually

- real camera list
- real site / building / floor / workshop / zone naming
- department ownership mapping
- employee master roster
- employee face images
- optional badge examples
- acceptance rules for closure, retention, and model promotion

## 4. Quick readiness commands

```bash
python scripts/doctor.py --ensure-scaffold
python scripts/check_supabase.py
python scripts/smoke_product.py
```

If `doctor.py` still reports missing checks, those are the exact keys and services still blocking full rollout.
