# Safety Helmet Productization Checklist

## 1. Current Snapshot

Inspection date: 2026-04-02

Current repo status is best described as:

- product feature completeness: medium-high
- local demo readiness: high
- production deployment readiness: medium-low

What is already in place:

- Streamlit operations console and monitoring worker are both present.
- Supabase schema split is relatively clear and has passed the current readiness check.
- Local smoke test can complete the alert -> workflow -> hard case loop.
- Unit tests currently pass.
- Evidence, workflow, notification log, and hard-case data models already exist.

What is still blocking product-grade rollout:

- no real authentication / trusted RBAC in the console
- secrets and camera source management are still too close to local config files
- production containerization and deployment packaging are not hardened yet
- runtime fallback behavior is convenient for demo use, but risky for production
- worker resilience, observability, and release automation are still thin

Recent local inspection highlights:

- `python scripts/doctor.py` reported Python `3.13.12`, while the project standard is Python `3.11` and fallback is `3.10`
- `python scripts/doctor.py` also reported missing `ultralytics` and `streamlit` in the active interpreter, plus incomplete local face stack
- `python scripts/check_supabase.py` reported `identity_extension=ready`, `identity_ai_extension=ready`, `product_extension=ready`, and `storage_bucket_ready=true`
- `python scripts/smoke_product.py` passed, but it validates a local fallback path rather than the formal cloud deployment path

## 2. Release Gate

Do not treat the project as production-ready until all `P0` items are complete.

Suggested release gates:

- `P0 complete`: eligible for controlled pilot rollout
- `P1 complete`: eligible for real field deployment in one site
- `P2 complete`: eligible for wider multi-site scaling

## 3. P0 Must Finish Before Pilot Rollout

### P0-1. Add real authentication and trusted RBAC

Current gap:

- `app.py` currently uses a sidebar role selector and free-text operator name.

Files involved:

- `app.py`
- future auth integration module under `src/helmet_monitoring/`

Required work:

- remove editable role switching from the UI
- derive operator identity from a trusted auth source
- enforce page-level and action-level permissions from server-side identity, not widget state
- add audit fields that use trusted user identity

Acceptance criteria:

- a user cannot self-upgrade to `admin`
- review, assignment, status update, and camera config edits are permission-checked
- audit logs contain trusted user identifiers

### P0-2. Separate secrets from runtime config

Current gap:

- camera `source` is edited directly in the UI and persisted to `runtime.json`
- RTSP credentials may appear in config examples and local files

Files involved:

- `app.py`
- `configs/runtime.example.json`
- `src/helmet_monitoring/core/config.py`

Required work:

- remove raw credential editing from the dashboard
- move camera credentials, SMTP passwords, and third-party keys into env vars or a secret manager
- redact sensitive values when displayed in the UI
- support secret references such as `env:CAMERA_RTSP_CAM_001`

Acceptance criteria:

- no plaintext RTSP password is stored in tracked config files
- no sensitive value is echoed back in the Streamlit UI
- production deployment can rotate secrets without editing committed JSON

### P0-3. Harden Docker packaging for production

Current gap:

- Docker runtime does not match the stated Python standard
- no `.dockerignore`
- compose file is still shaped like a dev convenience setup

Files involved:

- `Dockerfile`
- `docker-compose.yml`
- add `.dockerignore`
- `requirements.txt`
- `requirements.identity.txt`

Required work:

- align container Python version with the project standard
- add `.dockerignore` to exclude `.env`, `.venv`, `artifacts/`, `data/`, and local caches
- separate dev and prod compose behavior
- add health checks, restart policy, named volumes, and explicit runtime env handling
- pin dependency versions for reproducible builds

Acceptance criteria:

- repeated image builds are deterministic
- build context does not include secrets, datasets, or local artifacts
- `dashboard` and `monitor` services auto-restart on failure
- staging can be brought up from a clean machine with documented steps

### P0-4. Remove silent production fallback behavior

Current gap:

- repository layer can silently downgrade to local storage when Supabase is unavailable or schema is incomplete

Files involved:

- `src/helmet_monitoring/storage/repository.py`
- `scripts/check_supabase.py`
- `scripts/doctor.py`

Required work:

- introduce a strict production mode such as `ALLOW_LOCAL_FALLBACK=false`
- fail fast when the configured backend is `supabase` but the deployment is degraded
- surface degraded mode in the UI and startup logs
- keep local fallback only for explicit dev/test modes

Acceptance criteria:

- production startup fails loudly when the cloud backend is broken
- no alert data is silently split across Supabase and local JSONL in production
- readiness checks clearly show effective mode and degradation reason

### P0-5. Make the worker resilient to per-camera and per-step failures

Current gap:

- one unexpected exception in detect / identity / evidence / notification can interrupt the full worker loop

Files involved:

- `src/helmet_monitoring/services/monitor.py`
- `src/helmet_monitoring/services/video_sources.py`
- `src/helmet_monitoring/services/notifier.py`
- `src/helmet_monitoring/storage/evidence_store.py`

Required work:

- wrap per-camera processing in isolated error handling
- record structured error logs instead of relying on `print`
- distinguish camera offline, detection failure, persistence failure, and notification failure
- continue processing healthy cameras when one source fails

Acceptance criteria:

- one bad camera stream does not stop the whole worker
- one failed email send does not drop the alert record
- logs make the failing stage explicit

### P0-6. Add a real CI/CD baseline

Current gap:

- repository does not currently show a CI workflow

Files involved:

- add `.github/workflows/ci.yml` or equivalent pipeline

Required work:

- run tests on push / PR
- validate config syntax
- build Docker image in CI
- run at least one smoke path in CI

Acceptance criteria:

- every change has an automated validation path
- main branch cannot drift away from a buildable state

## 4. P1 Must Finish Before Real Field Deployment

### P1-1. Convert SQL rollout into a versioned migration process

Files involved:

- `sql/*.sql`

Required work:

- define migration ordering and environment promotion flow
- stop relying on manual SQL copy-paste in Supabase editor
- add schema version tracking

Acceptance criteria:

- staging and production schema state can be reproduced exactly

### P1-2. Build staging-grade cloud smoke tests

Files involved:

- `scripts/smoke_product.py`
- `scripts/check_supabase.py`
- add a new staging smoke script if needed

Required work:

- add a cloud smoke path that actually uses Supabase and storage
- optionally add SMTP sandbox verification
- keep local smoke as a separate dev/test path

Acceptance criteria:

- a release can prove the formal deployment path, not only the local fallback path

### P1-3. Add observability and operations telemetry

Files involved:

- `src/helmet_monitoring/services/monitor.py`
- `app.py`

Required work:

- structured logs
- camera health metrics
- per-stage failure counters
- event throughput and latency metrics
- degraded mode indicators in dashboard

Acceptance criteria:

- operators can answer "which camera failed", "when", and "why" within minutes

### P1-4. Operationalize identity stack deployment profiles

Files involved:

- `configs/runtime.example.json`
- `requirements.identity.txt`
- `src/helmet_monitoring/services/face_recognition.py`
- `src/helmet_monitoring/services/badge_ocr.py`

Required work:

- define CPU profile and GPU profile separately
- document which identity features are optional vs mandatory
- make defaults safe for machines without CUDA

Acceptance criteria:

- a fresh deployment does not default into unavailable GPU assumptions
- operators know exactly which extra packages are needed for each deployment profile

### P1-5. Tighten evidence governance and access control

Files involved:

- `src/helmet_monitoring/storage/evidence_store.py`
- `scripts/enforce_retention.py`

Required work:

- verify bucket privacy rules
- enforce signed URL behavior in production
- document retention and deletion workflow
- clarify who can access snapshots, crops, and clips

Acceptance criteria:

- evidence access is auditable and time-bounded
- retention behavior matches policy and can be verified

## 5. P2 Must Finish Before Wider Scaling

### P2-1. Build formal model promotion workflow

Files involved:

- `scripts/train_yolo.py`
- `docs/model_training_plan.md`
- hard-case collection directories under `data/`

Required work:

- define holdout dataset and pass/fail thresholds
- promote models only after offline and pilot validation
- record version, metrics, and rollout decision

Acceptance criteria:

- model promotion is based on repeatable evidence, not ad-hoc judgment

### P2-2. Add multi-camera scaling strategy

Required work:

- define worker concurrency model
- define per-site resource sizing
- benchmark RTSP throughput, clip writing, and identity stack cost

Acceptance criteria:

- deployment limits are documented for CPU-only and GPU-enabled nodes

### P2-3. Add disaster recovery and backup SOP

Required work:

- define backup scope for config, DB, and evidence metadata
- document recovery order for a failed deployment

Acceptance criteria:

- team can recover a site without relying on tribal knowledge

## 6. Suggested Implementation Order

Recommended sequence:

1. auth / RBAC
2. secrets and config separation
3. Docker and dependency hardening
4. strict backend mode
5. worker resilience
6. CI/CD baseline
7. staging smoke and observability

## 7. Suggested Immediate Next Sprint

If only one sprint is available, prioritize these deliverables:

- remove fake role switching from the dashboard
- add `.dockerignore` and align Docker Python version
- introduce strict Supabase mode without silent local fallback
- add per-camera exception isolation in the worker
- add a minimal CI workflow running tests and Docker build

## 8. Definition of Done for "Pilot Ready"

The project can be called "pilot ready" only if all of the following are true:

- authentication is real
- secrets are no longer stored in tracked config
- production images build reproducibly
- worker does not die from one camera or one notification error
- cloud backend failures are explicit, not silently downgraded
- staging smoke validates Supabase, storage, and the core alert path
