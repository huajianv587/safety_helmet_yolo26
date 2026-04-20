from __future__ import annotations

from helmet_monitoring.core.config import AppSettings, CameraSettings
from helmet_monitoring.core.schemas import AlertCandidate, ResolvedPerson
from helmet_monitoring.services.badge_ocr import LocalBadgeOcrService
from helmet_monitoring.services.face_recognition import FaceRecognitionService
from helmet_monitoring.services.llm_fallback import LlmFallbackService
from helmet_monitoring.services.person_directory import PersonDirectory


def _person_to_result(
    settings: AppSettings,
    camera: CameraSettings,
    person: dict | None,
    *,
    identity_status: str,
    identity_source: str,
    identity_confidence: float | None,
    badge_text: str | None = None,
    badge_confidence: float | None = None,
    face_match_score: float | None = None,
    review_note: str | None = None,
    llm_provider: str | None = None,
    llm_summary: str | None = None,
    face_crop=None,
    badge_crop=None,
) -> ResolvedPerson:
    if person:
        return ResolvedPerson(
            person_id=person.get("person_id"),
            person_name=person.get("name", settings.identity.unknown_person_name),
            employee_id=person.get("employee_id"),
            department=person.get("department", camera.department),
            team=person.get("team"),
            role=person.get("role"),
            phone=person.get("phone"),
            identity_status=identity_status,
            identity_source=identity_source,
            identity_confidence=identity_confidence,
            badge_text=badge_text,
            badge_confidence=badge_confidence,
            face_match_score=face_match_score,
            review_note=review_note,
            llm_provider=llm_provider,
            llm_summary=llm_summary,
            face_crop=face_crop,
            badge_crop=badge_crop,
        )
    return ResolvedPerson(
        person_id=None,
        person_name=settings.identity.unknown_person_name,
        employee_id=None,
        department=camera.department,
        team=None,
        role=None,
        phone=None,
        identity_status=identity_status,
        identity_source=identity_source,
        identity_confidence=identity_confidence,
        badge_text=badge_text,
        badge_confidence=badge_confidence,
        face_match_score=face_match_score,
        review_note=review_note,
        llm_provider=llm_provider,
        llm_summary=llm_summary,
        face_crop=face_crop,
        badge_crop=badge_crop,
    )


class IdentityResolver:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.directory = PersonDirectory(settings)
        self.badge_ocr = LocalBadgeOcrService(settings)
        self.face_recognition = FaceRecognitionService(settings)
        self.llm_fallback = LlmFallbackService(settings)

    def _resolve_camera_default(self, camera: CameraSettings) -> tuple[dict | None, str | None, float | None, str | None]:
        explicit = self.directory.get_person_by_id(camera.default_person_id)
        if explicit:
            return (
                explicit,
                "camera_default_registry",
                0.35,
                "Resolved by the explicit camera default person rule because OCR/face matching did not finalize.",
            )
        suggested = self.directory.suggest_default_person_for_camera(camera)
        if suggested:
            return (
                suggested,
                "camera_default_registry_match",
                float(suggested.get("_default_match_score", 0.42)) / 10.0,
                "Resolved by registry camera-binding metadata because OCR/face matching did not finalize.",
            )
        return None, None, None, None

    def _resolve_from_badge(self, raw_text: str | None) -> tuple[dict | None, list[dict]]:
        if not raw_text:
            return None, []
        candidates = self.directory.search_candidates(raw_text, limit=self.settings.llm_fallback.max_candidates)
        if not candidates:
            return None, []
        top = candidates[0]
        if top.get("_match_score", 0) >= 0.96:
            return top, candidates
        return None, candidates

    def resolve(self, camera: CameraSettings, candidate: AlertCandidate, frame) -> ResolvedPerson:
        badge_result = self.badge_ocr.recognize(frame, candidate.bbox)
        face_match = self.face_recognition.match(frame, candidate.bbox, self.directory.get_face_profiles())

        badge_person = self.directory.find_by_employee_id(badge_result.employee_id_hint)
        badge_candidates: list[dict] = []
        if badge_person is None and badge_result.text:
            badge_person, badge_candidates = self._resolve_from_badge(badge_result.text)

        llm_result = None
        llm_person = None
        if badge_person is None and badge_result.text and badge_candidates:
            llm_result = self.llm_fallback.resolve_badge_candidates(badge_result.text, badge_candidates)
            if llm_result and llm_result.person_id:
                llm_person = self.directory.get_person_by_id(llm_result.person_id)
            if llm_person is None and llm_result and llm_result.employee_id:
                llm_person = self.directory.find_by_employee_id(llm_result.employee_id)

        if badge_person and face_match.person and badge_person.get("person_id") == face_match.person.get("person_id"):
            confidence = max(badge_result.confidence or 0.0, face_match.similarity or 0.0)
            return _person_to_result(
                self.settings,
                camera,
                badge_person,
                identity_status="resolved",
                identity_source="badge_ocr+face_recognition",
                identity_confidence=round(confidence, 4),
                badge_text=badge_result.text,
                badge_confidence=badge_result.confidence,
                face_match_score=face_match.similarity,
                face_crop=face_match.crop,
                badge_crop=badge_result.crop,
            )

        if badge_person and face_match.person and badge_person.get("person_id") != face_match.person.get("person_id"):
            return _person_to_result(
                self.settings,
                camera,
                badge_person,
                identity_status="review_required",
                identity_source="badge_ocr_face_conflict",
                identity_confidence=max(badge_result.confidence or 0.0, face_match.similarity or 0.0),
                badge_text=badge_result.text,
                badge_confidence=badge_result.confidence,
                face_match_score=face_match.similarity,
                review_note=(
                    "Badge OCR and face recognition point to different people. Manual review is required "
                    "before auto-resolve can continue."
                ),
                face_crop=face_match.crop,
                badge_crop=badge_result.crop,
            )

        if badge_person:
            return _person_to_result(
                self.settings,
                camera,
                badge_person,
                identity_status="resolved",
                identity_source="badge_ocr",
                identity_confidence=badge_result.confidence,
                badge_text=badge_result.text,
                badge_confidence=badge_result.confidence,
                face_match_score=face_match.similarity,
                face_crop=face_match.crop,
                badge_crop=badge_result.crop,
            )

        if face_match.person and not face_match.review_required:
            return _person_to_result(
                self.settings,
                camera,
                face_match.person,
                identity_status="resolved",
                identity_source="face_recognition",
                identity_confidence=face_match.similarity,
                badge_text=badge_result.text,
                badge_confidence=badge_result.confidence,
                face_match_score=face_match.similarity,
                face_crop=face_match.crop,
                badge_crop=badge_result.crop,
            )

        if llm_person:
            return _person_to_result(
                self.settings,
                camera,
                llm_person,
                identity_status="review_required" if (llm_result and (llm_result.confidence or 0) < 0.8) else "resolved",
                identity_source="badge_ocr_llm",
                identity_confidence=llm_result.confidence if llm_result else None,
                badge_text=badge_result.text,
                badge_confidence=badge_result.confidence,
                face_match_score=face_match.similarity,
                review_note=llm_result.summary if llm_result else None,
                llm_provider=llm_result.provider if llm_result else None,
                llm_summary=llm_result.summary if llm_result else None,
                face_crop=face_match.crop,
                badge_crop=badge_result.crop,
            )

        if face_match.person and face_match.review_required:
            margin_note = ""
            if face_match.top1_margin is not None:
                margin_note = (
                    f" Top-1 margin {face_match.top1_margin:.2f} is below the auto-confirm gate "
                    f"{self.settings.governance.review_confidence_margin:.2f}."
                )
            return _person_to_result(
                self.settings,
                camera,
                face_match.person,
                identity_status="review_required",
                identity_source="face_recognition_review",
                identity_confidence=face_match.similarity,
                badge_text=badge_result.text,
                badge_confidence=badge_result.confidence,
                face_match_score=face_match.similarity,
                review_note=f"Face identity needs manual review before auto-confirm.{margin_note}",
                face_crop=face_match.crop,
                badge_crop=badge_result.crop,
            )

        default_person, default_source, default_confidence, default_note = self._resolve_camera_default(camera)
        if default_person:
            return _person_to_result(
                self.settings,
                camera,
                default_person,
                identity_status="review_required",
                identity_source=default_source or "camera_default_registry",
                identity_confidence=default_confidence,
                badge_text=badge_result.text,
                badge_confidence=badge_result.confidence,
                face_match_score=face_match.similarity,
                review_note=default_note,
                face_crop=face_match.crop,
                badge_crop=badge_result.crop,
            )

        return _person_to_result(
            self.settings,
            camera,
            None,
            identity_status="unresolved",
            identity_source="none",
            identity_confidence=None,
            badge_text=badge_result.text,
            badge_confidence=badge_result.confidence,
            face_match_score=face_match.similarity,
            review_note="No reliable badge or face identity match was found.",
            llm_provider=llm_result.provider if llm_result else None,
            llm_summary=llm_result.summary if llm_result else None,
            face_crop=face_match.crop,
            badge_crop=badge_result.crop,
        )


def build_identity_resolver(settings: AppSettings) -> IdentityResolver:
    return IdentityResolver(settings)
