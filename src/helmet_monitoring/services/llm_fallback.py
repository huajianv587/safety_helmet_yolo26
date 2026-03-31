from __future__ import annotations

import json
import os
from dataclasses import dataclass

import httpx

from helmet_monitoring.core.config import AppSettings


@dataclass(slots=True)
class LlmResolutionResult:
    person_id: str | None
    employee_id: str | None
    person_name: str | None
    confidence: float | None
    provider: str
    summary: str | None


class LlmFallbackService:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.deepseek_key = os.getenv("DEEPSEEK_API_KEY", "").strip()

    def _parse_json_text(self, content: str) -> dict | None:
        raw = content.strip()
        if not raw:
            return None
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:].strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(raw[start : end + 1])
                except json.JSONDecodeError:
                    return None
            return None

    def _build_prompt(self, raw_text: str, candidates: list[dict]) -> tuple[str, str]:
        system_prompt = (
            "You normalize employee badge OCR outputs. "
            "Return strict JSON with keys person_id, employee_id, person_name, confidence, summary. "
            "Only choose a candidate from the provided candidate list. "
            "If nothing is reliable, return nulls and confidence 0."
        )
        user_prompt = json.dumps(
            {
                "raw_badge_text": raw_text,
                "candidates": [
                    {
                        "person_id": item.get("person_id"),
                        "employee_id": item.get("employee_id"),
                        "name": item.get("name"),
                        "department": item.get("department"),
                        "team": item.get("team"),
                        "role": item.get("role"),
                        "match_score": item.get("_match_score"),
                    }
                    for item in candidates[: self.settings.llm_fallback.max_candidates]
                ],
            },
            ensure_ascii=False,
        )
        return system_prompt, user_prompt

    def _call_openai(self, system_prompt: str, user_prompt: str) -> LlmResolutionResult | None:
        if not (self.settings.llm_fallback.enabled and self.settings.llm_fallback.use_openai and self.openai_key):
            return None
        payload = {
            "model": self.settings.llm_fallback.openai_model,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
                {"role": "user", "content": [{"type": "input_text", "text": user_prompt}]},
            ],
        }
        response = httpx.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {self.openai_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.settings.llm_fallback.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        text = data.get("output_text")
        if not text:
            text_parts: list[str] = []
            for output_item in data.get("output", []):
                for content_item in output_item.get("content", []):
                    text_value = content_item.get("text")
                    if text_value:
                        text_parts.append(text_value)
            text = "\n".join(text_parts)
        parsed = self._parse_json_text(text or "")
        if not parsed:
            return None
        return LlmResolutionResult(
            person_id=parsed.get("person_id"),
            employee_id=parsed.get("employee_id"),
            person_name=parsed.get("person_name"),
            confidence=float(parsed.get("confidence", 0) or 0),
            provider="openai",
            summary=parsed.get("summary"),
        )

    def _call_deepseek(self, system_prompt: str, user_prompt: str) -> LlmResolutionResult | None:
        if not (self.settings.llm_fallback.enabled and self.settings.llm_fallback.use_deepseek and self.deepseek_key):
            return None
        payload = {
            "model": self.settings.llm_fallback.deepseek_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }
        response = httpx.post(
            "https://api.deepseek.com/chat/completions",
            headers={
                "Authorization": f"Bearer {self.deepseek_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.settings.llm_fallback.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        parsed = self._parse_json_text(content or "")
        if not parsed:
            return None
        return LlmResolutionResult(
            person_id=parsed.get("person_id"),
            employee_id=parsed.get("employee_id"),
            person_name=parsed.get("person_name"),
            confidence=float(parsed.get("confidence", 0) or 0),
            provider="deepseek",
            summary=parsed.get("summary"),
        )

    def resolve_badge_candidates(self, raw_text: str, candidates: list[dict]) -> LlmResolutionResult | None:
        if not raw_text or not candidates or not self.settings.llm_fallback.enabled:
            return None
        system_prompt, user_prompt = self._build_prompt(raw_text, candidates)
        for caller in (self._call_openai, self._call_deepseek):
            try:
                result = caller(system_prompt, user_prompt)
            except Exception as exc:  # pragma: no cover - network path
                print(f"[llm] provider failed: {exc}")
                continue
            if result and result.confidence and result.confidence > 0:
                return result
        return None
