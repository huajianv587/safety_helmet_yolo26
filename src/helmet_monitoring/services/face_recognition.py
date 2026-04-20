from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from helmet_monitoring.core.config import AppSettings
from helmet_monitoring.services.person_directory import FaceProfileRecord

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

try:
    import torch
    from facenet_pytorch import InceptionResnetV1, MTCNN
except ImportError:  # pragma: no cover
    torch = None
    InceptionResnetV1 = None
    MTCNN = None


@dataclass(slots=True)
class FaceMatchResult:
    person: dict | None
    similarity: float | None
    crop: object | None
    provider: str
    review_required: bool = False
    second_best_similarity: float | None = None
    top1_margin: float | None = None


class FaceRecognitionService:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.provider = "none"
        self.mtcnn = None
        self.model = None
        face_settings = settings.face_recognition
        if (
            not face_settings.enabled
            or MTCNN is None
            or InceptionResnetV1 is None
            or torch is None
            or Image is None
        ):
            return
        device = face_settings.device
        if device != "cpu" and not torch.cuda.is_available():
            device = "cpu"
        self.device = device
        self.mtcnn = MTCNN(image_size=160, margin=14, keep_all=False, post_process=True, device=device)
        self.model = InceptionResnetV1(pretrained="vggface2").eval().to(device)
        self.provider = "facenet_pytorch"

    def _crop_person_roi(self, frame, bbox: dict[str, int]):
        height, width = frame.shape[:2]
        x1 = max(0, bbox["x1"])
        y1 = max(0, bbox["y1"])
        x2 = min(width, bbox["x2"])
        y2 = min(height, bbox["y2"])
        person_height = max(1, y2 - y1)
        top = max(0, y1 - int(person_height * 0.05))
        bottom = min(height, y1 + int(person_height * 0.55))
        crop = frame[top:bottom, x1:x2].copy()
        return crop if crop.size else None

    def _encode_crop(self, crop):
        if self.mtcnn is None or self.model is None:
            return None, None
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        boxes, probs = self.mtcnn.detect(image)
        if boxes is None or len(boxes) == 0:
            return None, None
        best_idx = int(np.argmax(probs))
        box = boxes[best_idx]
        x1, y1, x2, y2 = [max(0, int(value)) for value in box]
        face_crop = crop[y1:y2, x1:x2].copy()
        if face_crop.size == 0:
            return None, None
        face_tensor = self.mtcnn(Image.fromarray(cv2.cvtColor(face_crop, cv2.COLOR_BGR2RGB)))
        if face_tensor is None:
            return None, None
        embedding = self.model(face_tensor.unsqueeze(0).to(self.device)).detach().cpu().numpy()[0].astype(np.float32)
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        return embedding, face_crop

    def match(self, frame, bbox: dict[str, int], profiles: list[FaceProfileRecord]) -> FaceMatchResult:
        if self.provider == "none" or not profiles:
            return FaceMatchResult(person=None, similarity=None, crop=None, provider="none")
        crop = self._crop_person_roi(frame, bbox)
        if crop is None:
            return FaceMatchResult(person=None, similarity=None, crop=None, provider=self.provider)
        embedding, face_crop = self._encode_crop(crop)
        if embedding is None:
            return FaceMatchResult(person=None, similarity=None, crop=None, provider=self.provider)
        ranked_matches: list[tuple[float, FaceProfileRecord]] = []
        for profile in profiles:
            similarity = float(np.dot(embedding, profile.embedding))
            ranked_matches.append((similarity, profile))
        ranked_matches.sort(key=lambda item: item[0], reverse=True)
        best_similarity, best_profile = ranked_matches[0] if ranked_matches else (None, None)
        if best_profile is None or best_similarity is None:
            return FaceMatchResult(person=None, similarity=None, crop=face_crop, provider=self.provider)
        second_best_similarity = ranked_matches[1][0] if len(ranked_matches) > 1 else None
        top1_margin = (
            float(best_similarity - second_best_similarity)
            if second_best_similarity is not None
            else float(best_similarity)
        )
        threshold = self.settings.face_recognition.similarity_threshold
        review_threshold = self.settings.face_recognition.review_threshold
        review_margin = self.settings.governance.review_confidence_margin
        if best_similarity >= threshold and top1_margin >= review_margin:
            return FaceMatchResult(
                person=best_profile.person,
                similarity=round(best_similarity, 4),
                crop=face_crop,
                provider=self.provider,
                review_required=False,
                second_best_similarity=round(second_best_similarity, 4) if second_best_similarity is not None else None,
                top1_margin=round(top1_margin, 4),
            )
        return FaceMatchResult(
            person=best_profile.person if best_similarity >= review_threshold else None,
            similarity=round(best_similarity, 4),
            crop=face_crop,
            provider=self.provider,
            review_required=best_similarity >= review_threshold,
            second_best_similarity=round(second_best_similarity, 4) if second_best_similarity is not None else None,
            top1_margin=round(top1_margin, 4),
        )
