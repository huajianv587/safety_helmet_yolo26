# Safety Helmet Industrialization Blueprint

## 1. Current repo status

This repo already contains the backbone of a product system:

- Streamlit control console
- monitoring worker
- alert workflow and audit logs
- evidence snapshot / crop / clip chain
- Supabase schema split into phase1 + identity + AI identity + product extension
- local fallback repository
- unit tests for event, governance, identity and workflow rules

The main remaining gaps are not only code bugs, but operational closure:

- cloud credentials are not connected in the current environment
- real camera sources are not enabled for production use
- personnel master data and face samples are not yet fully operationalized
- training and hard-case feedback loop is not yet formalized as a standard workflow
- readiness inspection and deterministic smoke validation were missing before this round

## 2. What was added in this round

- `scripts/bootstrap_workspace.py`
- `scripts/doctor.py`
- `scripts/smoke_product.py`
- `scripts/train_yolo.py`
- fixed `scripts/sync_person_registry.py`
- fixed `scripts/register_face_profiles.py`
- updated `scripts/smoke_phase1.py` to forward to the current smoke flow

## 3. Full closure definition

An industrial closed loop for this project means one alert can go through:

1. camera capture
2. detection and event judgment
3. identity resolution or review-required marking
4. evidence persistence
5. alert creation with unique `event_no`
6. notification dispatch or logged skip
7. manual review / assign / correction
8. final closure status
9. hard-case return when false positive
10. audit log retention

The repo now supports a deterministic local simulation for steps 2-10:

```bash
python scripts/smoke_product.py
```

## 4. Immediate production priorities

### P0 Must finish before field rollout

- fill `.env` with real Supabase and SMTP values
- run all SQL in Supabase
- enable at least one real camera in `configs/runtime.json`
- run `python scripts/check_supabase.py`
- run `python scripts/doctor.py --ensure-scaffold`
- run `python scripts/smoke_product.py`
- run real monitor with `.venv\Scripts\python.exe scripts\run_monitor.py`
- open `streamlit run app.py`

### P1 Must finish before real identity closure

- complete `configs/person_registry.json`
- sync persons to Supabase
- collect face photos by `person_id`
- run `python scripts/register_face_profiles.py`
- decide whether OCR uses PaddleOCR or RapidOCR
- provide OpenAI or DeepSeek key for ambiguous badge fallback

### P2 Must finish before model promotion

- build hard-case folders and collection SOP
- define train / val / site-holdout split
- add missed-detection and false-positive datasets from your own site
- train at least one candidate model
- compare on offline holdout and live pilot video
- promote only after threshold pass

## 5. Directory scaffold now expected

- `artifacts/captures`
- `artifacts/runtime`
- `artifacts/logs`
- `artifacts/reports`
- `artifacts/exports`
- `artifacts/identity/faces`
- `artifacts/identity/badges`
- `artifacts/identity/review`
- `data/hard_cases/false_positive`
- `data/hard_cases/missed_detection`
- `data/hard_cases/night_shift`
- `data/identity/faces`
- `data/identity/badges`

Create or refresh them by:

```bash
python scripts/bootstrap_workspace.py --copy-env-example --copy-registry-example
```

## 6. Recommended verification order

```bash
python scripts/bootstrap_workspace.py --copy-env-example --copy-registry-example
python scripts/doctor.py --ensure-scaffold
python scripts/check_supabase.py
python scripts/smoke_product.py
.venv\Scripts\python.exe scripts\smoke_product.py --use-model
.venv\Scripts\python.exe scripts\run_monitor.py
streamlit run app.py
```
