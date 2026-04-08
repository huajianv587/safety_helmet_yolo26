# forward_step.py 
# 
# This file is the next-step roadmap for the safety helmet system. 
# Read it as a project manager checklist. 
# 
# How to use 
# 1. Finish F01 to F05 first because they decide whether the system can land in the field. 
# 2. Then stabilize F06 to F10 so the model chain is reliable. 
# 3. Finally push F11 to F22 to complete industrialization and productization. 
# 
# F01 Alert workflow closure 
# Status: partial 
# Goal: run one real alert through pending, assigned, confirmed, remediated, false_positive, ignored. 
# Next: test one real case, define role permissions, define business meaning for every state. 
# Files: app.py, src/helmet_monitoring/services/workflow.py, sql/supabase_product_extension.sql 
# 
# F02 Evidence chain 
# Status: partial 
# Goal: every alert should have snapshot, crops, clip, event number, and timestamp watermark. 
# Next: validate clip generation on real RTSP, verify night and reconnect scenarios. 
# Files: src/helmet_monitoring/storage/evidence_store.py, src/helmet_monitoring/services/clip_recorder.py, src/helmet_monitoring/services/monitor.py 
# 
# F03 Manual review desk 
# Status: partial 
# Goal: operators can review, reassign, fix identity, and close the case from UI only. 
# Next: let real admins use the page and collect workflow feedback. 
# Files: app.py, src/helmet_monitoring/services/workflow.py, src/helmet_monitoring/storage/repository.py 
# 
# F04 Notification center 
# Status: partial 
# Goal: real alert emails reach the right recipients. 
# Next: fill SMTP fields in .env, set ALERT_EMAIL_RECIPIENTS, run a real delivery test. 
# Files: .env, app.py, src/helmet_monitoring/services/notifier.py
# 
# F05 Camera management 
# Status: partial 
# Goal: operators can see online state, heartbeat, reconnect count, retry count, fps, and last error. 
# Next: register real cameras, test one real RTSP disconnect and reconnect cycle. 
# Files: app.py, configs/runtime.json, src/helmet_monitoring/services/video_sources.py 
# 
# F06 Cascade inference 
# Status: partial 
# Goal: detection, tracking, event judgment, and identity should run stably on real hardware. 
# Next: measure latency, CPU, GPU, and identity sub-pipeline cost. 
# Files: src/helmet_monitoring/services/monitor.py, src/helmet_monitoring/services/detector.py, src/helmet_monitoring/services/identity_resolver.py 
# 
# F07 False positive governance 
# Status: partial 
# Goal: reduce false positives with min_bbox_area, ignore_zones, whitelist cameras, night review. 
# Next: tune governance values on real site videos. 
# Files: configs/runtime.json, src/helmet_monitoring/services/governance.py 
# 
# F08 Tracking upgrade 
# Status: partial 
# Goal: compare builtin tracking with ultralytics_bytetrack and keep the more stable option. 
# Files: configs/runtime.example.json, src/helmet_monitoring/services/detector.py, src/helmet_monitoring/services/event_engine.py 
# 
# F09 Hard cases loop 
# Status: partial 
# Goal: collect false positives, night failures, backlight failures, and crowded-scene failures for next YOLO26 round. 
# Files: app.py, src/helmet_monitoring/services/workflow.py, sql/supabase_product_extension.sql 
# 
# F10 Identity fields discipline 
# Status: implemented 
# Goal: keep identity_source, identity_confidence, identity_status, and review_required discipline in every identity result. 
# Files: src/helmet_monitoring/services/identity_resolver.py, src/helmet_monitoring/core/schemas.py 
# 
# F11 Multi-level organization 
# F12 Permission system 
# F13 Reports 
# F14 Work-order style alert detail 
# F15 Search and filtering enhancement 
# F16 Edge inference and center management split 
# F17 Stream layer upgrade to FFmpeg or GStreamer 
# F18 Service split monitor dashboard notifier api 
# F19 Ops metrics 
# F20 Container deployment 
# F21 Private storage and signed url enablement 
# F22 Sensitive data retention and audit execution 
# 
# Recommended order 
# Batch 1: run SQL, fill .env, connect RTSP, run SMTP, finish one full workflow. 
# Batch 2: train YOLO26, collect hard cases, register face samples, validate badge OCR. 
# Batch 3: move toward edge deployment, stream upgrade, service split, strict permissions.
# 
# F11 Multi-level organization 
# Status: partial 
# Goal: every alert belongs to site, building, floor, workshop, and zone. 
# Next: fill real hierarchy metadata for every camera and standardize naming. 
# 
# F12 Permission system 
# Status: partial 
# Goal: different roles must see different pages, actions, and data scopes. 
# Next: define exact permission matrix and move checks into backend later. 
# 
# F13 Reports and analytics 
# Status: partial 
# Goal: define daily and weekly metrics that managers actually care about. 
# Next: finalize closure rate, false positive rate, department ranking, and person ranking definitions. 
# 
# F14 Work-order style detail page 
# Status: partial 
# Goal: one alert page should show enough context for decision, reassignment, and closure. 
# Next: add historical violation counts and more case context. 
# 
# F15 Search and filtering 
# Status: partial 
# Goal: operators can find one alert fast in a large event list. 
# Next: add risk, hierarchy, and more date filters. 
# 
# F16 Edge and center split 
# Status: planned 
# Goal: run worker near cameras and keep UI plus database at the center. 
# Next: define what belongs to edge and what belongs to center. 
# 
# F17 Stream layer upgrade 
# Status: planned 
# Goal: move long-run RTSP handling toward FFmpeg or GStreamer. 
# Next: test one real RTSP source with a stronger stream layer. 
# 
# F18 Service split 
# Status: planned 
# Goal: separate monitor, dashboard, notifier, and later API as isolated services. 
# Next: use docker compose first, then split deeper only when needed. 
# 
# F19 Ops metrics 
# Status: partial 
# Goal: monitor latency, reconnects, storage failures, email failures, and worker health. 
# Next: expose more runtime metrics and later connect Prometheus or Grafana. 
# 
# F20 Container deployment 
# Status: partial 
# Goal: bring the system up on a new machine with minimal manual work. 
# Next: run docker compose end to end with your real runtime settings. 
# 
# F21 Private storage and signed urls 
# Status: partial 
# Goal: stop exposing evidence files publicly in formal deployment. 
# Next: switch to private bucket and verify signed url display in UI. 
# 
# F22 Sensitive data retention and audit 
# Status: partial 
# Goal: face data and evidence data must have retention, deletion, and access audit. 
# Next: set retention days and run enforce_retention.py on schedule.
