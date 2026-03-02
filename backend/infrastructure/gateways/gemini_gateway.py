"""Gemini API gateway — thin JSON-returning LLM wrapper."""

from __future__ import annotations

import json
import logging
import time

from common.config import GEMINI_API_KEY

logger = logging.getLogger(__name__)


class GeminiGateway:
    """Wraps Google Gemini API calls. Returns parsed JSON."""

    def __init__(self, model: str = "gemini-2.5-flash"):
        self._model = model

    def call(self, prompt: str, model: str | None = None, task: str | None = None) -> dict:
        """Send a prompt and return parsed JSON from the response."""
        from google import genai

        model_used = model or self._model
        client = genai.Client(api_key=GEMINI_API_KEY)

        if task:
            t0 = time.time()

        response = client.models.generate_content(
            model=model_used,
            contents=prompt,
        )
        raw = response.text.strip()
        result = self._extract_json(raw)

        if task:
            latency_ms = int((time.time() - t0) * 1000)
            try:
                from backend.infrastructure.gateways.db_gateway import DbGateway
                DbGateway().log_classification(task, model_used, prompt, json.dumps(result), latency_ms)
            except Exception:
                logger.warning("Failed to log classification for task=%s", task, exc_info=True)

        return result

    @staticmethod
    def _extract_json(raw: str) -> dict:
        """Extract JSON object from LLM response (handles markdown fences)."""
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3].strip()
        if raw.startswith("{"):
            return json.loads(raw)
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(raw[start:end])
        return {"raw_parsed": raw}
