from __future__ import annotations

import re
from dataclasses import dataclass

import cv2

from helmet_monitoring.core.config import AppSettings, OcrSettings

try:
    from paddleocr import PaddleOCR
except ImportError:  # pragma: no cover
    PaddleOCR = None

try:
    from rapidocr_onnxruntime import RapidOCR
except ImportError:  # pragma: no cover
    RapidOCR = None


EMPLOYEE_ID_PATTERN = re.compile(r"[A-Z]?\s*\d{4,8}")


@dataclass(slots=True)
class BadgeOcrResult:
    text: str | None
    confidence: float | None
    provider: str
    employee_id_hint: str | None
    crop: object | None


def normalize_badge_text(text: str | None) -> str:
    if not text:
        return ""
    cleaned = text.replace("\n", " ").replace("\r", " ")
    return " ".join(cleaned.split()).strip()


def extract_employee_id(text: str | None) -> str | None:
    normalized = normalize_badge_text(text).upper()
    match = EMPLOYEE_ID_PATTERN.search(normalized)
    if not match:
        return None
    return "".join(ch for ch in match.group(0) if ch.isalnum())


class LocalBadgeOcrService:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.ocr_settings: OcrSettings = settings.ocr
        self.provider = "none"
        self.engine = None
        if not self.ocr_settings.enabled:
            return
        provider = self.ocr_settings.provider
        if provider in {"paddleocr", "auto"} and PaddleOCR is not None:
            try:
                try:
                    self.engine = PaddleOCR(use_angle_cls=False, lang="en", show_log=False)
                except (TypeError, ValueError):
                    # Newer PaddleOCR versions changed accepted constructor args.
                    self.engine = PaddleOCR(use_angle_cls=False, lang="en")
                self.provider = "paddleocr"
                return
            except Exception:
                self.engine = None
                self.provider = "none"
        if provider in {"rapidocr", "auto"} and RapidOCR is not None:
            self.engine = RapidOCR()
            self.provider = "rapidocr"

    def _crop_badge_roi(self, frame, bbox: dict[str, int]):
        height, width = frame.shape[:2]
        x1 = max(0, bbox["x1"])
        y1 = max(0, bbox["y1"])
        x2 = min(width, bbox["x2"])
        y2 = min(height, bbox["y2"])
        person_width = max(1, x2 - x1)
        person_height = max(1, y2 - y1)
        x_margin = int(person_width * self.ocr_settings.badge_roi_x_margin)
        badge_x1 = max(0, x1 + x_margin)
        badge_x2 = min(width, x2 - x_margin)
        badge_y1 = max(0, y1 + int(person_height * self.ocr_settings.badge_roi_y_start))
        badge_y2 = min(height, y1 + int(person_height * self.ocr_settings.badge_roi_y_end))
        if badge_x2 <= badge_x1 or badge_y2 <= badge_y1:
            return None
        crop = frame[badge_y1:badge_y2, badge_x1:badge_x2].copy()
        if crop.size == 0:
            return None
        resized = cv2.resize(crop, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        filtered = cv2.bilateralFilter(gray, 7, 40, 40)
        processed = cv2.adaptiveThreshold(
            filtered,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            11,
        )
        return cv2.cvtColor(processed, cv2.COLOR_GRAY2BGR)

    def recognize(self, frame, bbox: dict[str, int]) -> BadgeOcrResult:
        crop = self._crop_badge_roi(frame, bbox)
        if crop is None:
            return BadgeOcrResult(text=None, confidence=None, provider="none", employee_id_hint=None, crop=None)
        if self.engine is None:
            return BadgeOcrResult(text=None, confidence=None, provider="none", employee_id_hint=None, crop=crop)

        texts: list[str] = []
        scores: list[float] = []
        try:
            if self.provider == "paddleocr":
                output = self.engine.ocr(crop, cls=False)
                for block in output or []:
                    if not block:
                        continue
                    for line in block:
                        if not line or len(line) < 2:
                            continue
                        texts.append(str(line[1][0]))
                        scores.append(float(line[1][1]))
            elif self.provider == "rapidocr":
                output, _ = self.engine(crop)
                for line in output or []:
                    if len(line) < 3:
                        continue
                    texts.append(str(line[1]))
                    scores.append(float(line[2]))
        except Exception:
            return BadgeOcrResult(text=None, confidence=None, provider=self.provider, employee_id_hint=None, crop=crop)

        text = normalize_badge_text(" ".join(texts))
        confidence = (sum(scores) / len(scores)) if scores else None
        if confidence is not None and confidence < self.ocr_settings.min_confidence:
            text = None
        return BadgeOcrResult(
            text=text or None,
            confidence=round(float(confidence), 4) if confidence is not None else None,
            provider=self.provider,
            employee_id_hint=extract_employee_id(text),
            crop=crop,
        )
