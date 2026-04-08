# Model Training Plan

## 1. Which models you should train

### A. Main detector: helmet / no_helmet

Purpose:

- the core production model
- used by the monitoring worker
- directly affects false positives and missed detections

Current recommendation:

- start with a YOLO baseline already compatible with this repo
- keep labels minimal and stable:
  - `helmet`
  - `no_helmet`

Train with:

```bash
.venv\Scripts\python.exe scripts\train_yolo.py --epochs 80 --imgsz 640 --batch 16 --name train_product
```

### B. Optional identity support models

These are not trained in this repo first:

- badge OCR: use PaddleOCR or RapidOCR first
- face recognition: use facenet-pytorch embeddings first

Only consider custom training after your site data proves the generic stack is not enough.

## 2. Where data should come from

### Existing base data

- current repo already contains `data/helmet_detection_dataset`
- current dataset yaml: `configs/datasets/shwd_yolo26.yaml`

### Data you still need to add

- your own camera negatives
- backlight scenes
- night scenes
- crowded scenes
- partial body scenes
- hats mistaken as helmets
- missed detections from production
- false positives from production

Standardized folders:

- `data/hard_cases/false_positive`
- `data/hard_cases/missed_detection`
- `data/hard_cases/night_shift`
- `artifacts/identity/faces/<person_id>/`
- `data/identity/badges/<person_id>/`

## 3. Minimum production dataset strategy

Recommended split:

- train: 70%
- val: 20%
- site holdout: 10%

The holdout set should come from cameras and days not used in training.

## 4. Promotion criteria

Do not promote a model only because mAP looks better. Use:

- offline val precision / recall
- false positive rate on real pilot video
- missed detection rate on real pilot video
- latency on deployment hardware
- night scene stability
- crowded scene stability
- backlight stability

## 5. Operational commands

### Train

```bash
.venv\Scripts\python.exe scripts\train_yolo.py --data configs/datasets/shwd_yolo26.yaml --weights artifacts/models/yolov8n.pt --name train_product
```

### Smoke with trained model

```bash
.venv\Scripts\python.exe scripts\smoke_product.py --use-model
```

### Switch runtime to promoted model

Update `configs/runtime.json` and set `model.path` to the promoted `best.pt`.
