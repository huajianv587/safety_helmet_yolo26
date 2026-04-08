# teach_and_read.py 
# 
# This file explains the project structure and what each folder and file is doing. 
# Read this file side by side with the code in your IDE. 
# 
# Part 1. Root level files and folders 
# .env 
# Local runtime secrets and deployment settings. Fill this before real deployment. 
# .gitignore 
# Protects local secrets, runtime artifacts, training results, and dataset folders from git. 
# README.md 
# High level runbook. It explains setup, SQL order, docker compose, and runtime usage. 
# app.py 
# Streamlit product console. It is the main UI entry for overview, review desk, camera center, reports, notifications, and hard cases. 
# Dockerfile 
# Base container image for dashboard and worker. It installs ffmpeg and Python dependencies. 
# docker-compose.yml 
# Local multi-service deployment file. It starts dashboard and monitor as separate services. 
# requirements.txt 
# Core runtime dependencies. Keep this lean for the main system. 
# requirements.identity.txt 
# Optional OCR and face recognition packages. Use this in machines that need local identity inference. 
# forward_step.py 
# The roadmap file. It tells you what to do next. 
# teach_and_read.py 
# This guide file. 
# 
# data 
# Local dataset area. This is where training and validation images live. It is ignored by git. 
# artifacts 
# Local outputs such as captures, clips, runtime jsonl, models, and training results. It is ignored by git. 
# docs 
# Reserved for future formal product or deployment documentation. Currently empty. 
# legacy 
# Old YOLOv8 demo code kept only for reference. It is not the new main path. 
# configs 
# Runtime json files, dataset yaml files, env template, and person registry sample files. 
# scripts 
# Operational helpers. These files run checks, smoke tests, sync tasks, and worker entrypoints. 
# sql 
# Supabase schema files. Run them in order to unlock base tables, identity, and product tables. 
# src 
# Main application package. This is where the real business logic lives. 
# tests 
# Unit tests for event logic, OCR helpers, governance, identity resolver, and workflow rules.
# 
# Part 2. configs folder 
# configs/runtime.json 
# Your active runtime config. This file decides model path, cameras, notification settings, governance, clip settings, and security behavior. 
# configs/runtime.example.json 
# A richer reference config showing how a production style setup should look. 
# configs/supabase.example.env 
# Template env file for Supabase, SMTP, and LLM keys. 
# configs/person_registry.example.json 
# Example employee master file. Use it to understand person table shape. 
# configs/person_registry.json 
# Generated demo employee data used for testing identity and UI display. 
# configs/datasets/shwd_legacy.yaml 
# Old dataset yaml used by earlier training flow. 
# configs/datasets/shwd_yolo26.yaml 
# Dataset yaml prepared for YOLO26 training. 
# 
# Part 3. scripts folder 
# scripts/run_monitor.py 
# The worker entrypoint. This is how the monitoring loop is started from command line. 
# scripts/check_supabase.py 
# Fast health check for schema readiness and storage bucket readiness. 
# scripts/ensure_storage_bucket.py 
# Prepares the storage bucket before evidence upload tests. 
# scripts/smoke_evidence_upload.py 
# Minimal test that uploads one image into evidence storage. 
# scripts/smoke_phase1.py 
# Old smoke test for the original MVP flow using local repository and snapshot store. 
# scripts/generate_demo_persons.py 
# Builds 30 synthetic employees for demo and local testing. 
# scripts/sync_person_registry.py 
# Pushes person_registry.json into Supabase persons table. 
# scripts/register_face_profiles.py 
# Reads local face images and writes facenet embeddings into person_face_profiles. 
# scripts/enforce_retention.py 
# Local retention cleanup tool for old evidence files. 
# 
# Part 4. sql folder 
# sql/supabase_phase1_schema.sql 
# Creates the original cameras and alerts tables. 
# sql/supabase_identity_extension.sql 
# Adds persons table and alert identity fields such as person_name and employee_id. 
# sql/supabase_identity_ai_extension.sql 
# Adds face profile storage and AI identity evidence fields such as confidence and crop urls. 
# sql/supabase_product_extension.sql 
# Adds product tables for alert actions, notifications, hard cases, audit logs, and camera ops fields. 
# 
# Part 5. src/helmet_monitoring package overview 
# src/helmet_monitoring/__init__.py 
# Package version marker. 
# src/helmet_monitoring/core 
# Shared data model and config parsing layer. Start here before reading services. 
# src/helmet_monitoring/services 
# Runtime business logic. Detection, event judgment, identity, monitoring, clips, governance, workflow, and notifications are here. 
# src/helmet_monitoring/storage 
# Storage abstraction. Local files and Supabase persistence are managed here. 
# src/helmet_monitoring/ui 
# Reserved package for future dedicated UI modules. Currently only an init file. 
# src/helmet_monitoring/training 
# Reserved package for future training pipeline modules. Currently empty.
# 
# Part 6. core folder files 
# src/helmet_monitoring/core/config.py 
# The global settings parser. It merges .env values and runtime.json values into one AppSettings object. If you want to know what can be configured, read this file first. 
# src/helmet_monitoring/core/schemas.py 
# Shared dataclasses flowing through the whole system. DetectionRecord, AlertCandidate, AlertRecord, CameraHeartbeat, AlertActionRecord, NotificationLogRecord, and HardCaseRecord are all defined here. 
# src/helmet_monitoring/core/__init__.py 
# Empty package marker. 
# 
# Part 7. services folder files 
# src/helmet_monitoring/services/detector.py 
# Wraps the Ultralytics model. It runs detect or track, normalizes labels, and builds DetectionRecord objects. 
# src/helmet_monitoring/services/event_engine.py 
# Converts per-frame detections into event-level alerts using consecutive hits, distance matching, dedupe window, and track state. 
# src/helmet_monitoring/services/video_sources.py 
# Opens webcam or RTSP streams and keeps retry count, reconnect count, last fps, and last error. 
# src/helmet_monitoring/services/governance.py 
# The false positive control layer. It filters small targets, ignore zones, whitelist cameras, and night review cases. 
# src/helmet_monitoring/services/badge_ocr.py 
# Local badge OCR adapter. It crops the chest area, preprocesses it, runs OCR, and extracts employee id hints. 
# src/helmet_monitoring/services/face_recognition.py 
# Facenet based face matching service. It creates embeddings and compares them with stored employee profiles. 
# src/helmet_monitoring/services/person_directory.py 
# Loads persons and face profiles from Supabase or local registry and offers search and lookup helpers. 
# src/helmet_monitoring/services/llm_fallback.py 
# Calls OpenAI or DeepSeek only as a fallback to disambiguate noisy OCR text. It is not used as the main identity method. 
# src/helmet_monitoring/services/identity_resolver.py 
# Combines badge OCR, face recognition, LLM fallback, and camera default rule into one identity decision. 
# src/helmet_monitoring/services/clip_recorder.py 
# Buffers frames before and after the alert so one event can have a short evidence clip. 
# src/helmet_monitoring/services/notifier.py 
# Sends email notifications and writes notification logs. 
# src/helmet_monitoring/services/workflow.py 
# Applies business actions to an alert such as assign, remediated, false_positive, and also writes action history and audit logs. 
# src/helmet_monitoring/services/monitor.py 
# The main runtime orchestrator. This is the most important backend file. It ties cameras, detection, governance, identity, evidence, workflow, storage, and notifications together. 
# src/helmet_monitoring/services/__init__.py 
# Empty package marker. 
# 
# Part 8. storage folder files 
# src/helmet_monitoring/storage/repository.py 
# The storage abstraction layer. It knows how to write alerts, actions, notifications, hard cases, and audit logs to either Supabase or local fallback files. 
# src/helmet_monitoring/storage/evidence_store.py 
# Saves images and clips locally and optionally uploads them to Supabase Storage with public or signed urls. 
# src/helmet_monitoring/storage/snapshot_store.py 
# Older simple snapshot helper kept for old smoke tests. 
# src/helmet_monitoring/storage/__init__.py 
# Empty package marker. 
# 
# Part 9. tests folder files 
# tests/test_event_engine.py 
# Verifies consecutive hits and dedupe behavior. 
# tests/test_badge_ocr.py 
# Verifies OCR text normalization and employee id extraction. 
# tests/test_identity_resolver.py 
# Verifies badge based identity and camera default fallback logic. 
# tests/test_governance.py 
# Verifies whitelist and small-target governance rules. 
# tests/test_workflow.py 
# Verifies false_positive handling and hard case generation. 
# tests/__init__.py 
# Package marker for tests. 
# 
# Part 10. legacy folder files 
# legacy/legacy_train_yolov8.py 
# Old YOLOv8 training script. Read only if you want historical context. 
# legacy/legacy_streamlit_demo.py 
# Old demo UI. Useful only for comparison with the new product console. 
# legacy/legacy_camera_monitor.py 
# Old camera loop before the new industrial worker existed. 
# legacy/legacy_convert_dataset.py 
# Old dataset conversion helper. 
# legacy/README_legacy_deployment.txt 
# Historical deployment notes from the old version. 
# 
# Recommended reading order 
# 1. .env 
# 2. configs/runtime.json 
# 3. README.md 
# 4. app.py 
# 5. src/helmet_monitoring/core/config.py 
# 6. src/helmet_monitoring/core/schemas.py 
# 7. src/helmet_monitoring/storage/repository.py 
# 8. src/helmet_monitoring/services/monitor.py 
# 9. src/helmet_monitoring/services/detector.py 
# 10. src/helmet_monitoring/services/event_engine.py 
# 11. src/helmet_monitoring/services/governance.py 
# 12. src/helmet_monitoring/services/identity_resolver.py 
# 13. src/helmet_monitoring/services/person_directory.py 
# 14. src/helmet_monitoring/services/badge_ocr.py and src/helmet_monitoring/services/face_recognition.py 
# 15. src/helmet_monitoring/services/workflow.py and src/helmet_monitoring/services/notifier.py 
# 16. scripts and sql folder files 
# 17. tests folder to understand the expected behavior.
