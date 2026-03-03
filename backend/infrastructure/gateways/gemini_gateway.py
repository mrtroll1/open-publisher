"""Gemini API gateway — thin JSON-returning LLM wrapper."""

from __future__ import annotations

import json
import logging

from common.config import GEMINI_API_KEY

logger = logging.getLogger(__name__)


class GeminiGateway:
    """Wraps Google Gemini API calls. Returns parsed JSON."""

    def __init__(self, model: str = "gemini-2.5-flash"):
        self._model = model

    def call(self, prompt: str, model: str | None = None) -> dict:
        """Send a prompt and return parsed JSON from the response."""
        from google import genai

        model_used = model or self._model
        client = genai.Client(api_key=GEMINI_API_KEY)

        response = client.models.generate_content(
            model=model_used,
            contents=prompt,
        )
        raw = response.text.strip()
        return self._extract_json(raw)

    @staticmethod
    def _extract_json(raw: str) -> dict:
        """Extract JSON object from LLM response (handles markdown fences)."""
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3].strip()

        def _try_loads(s: str) -> dict:
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                cleaned = s.replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n").replace("\t", "\\t")
                return json.loads(cleaned)

        if raw.startswith("{"):
            return _try_loads(raw)
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            return _try_loads(raw[start:end])
        return {"raw_parsed": raw}
