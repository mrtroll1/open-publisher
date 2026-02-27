"""Gemini API gateway — LLM calls for parsing and translation."""

from __future__ import annotations

import json
import logging

from common.config import GEMINI_API_KEY

logger = logging.getLogger(__name__)


class GeminiGateway:
    """Wraps Google Gemini API calls."""

    def __init__(self, model: str = "gemini-2.5-flash"):
        self._model = model

    def _call(self, prompt: str) -> str:
        """Make a synchronous Gemini API call. Returns raw response text."""
        from google import genai

        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model=self._model,
            contents=prompt,
        )
        return response.text.strip()

    def parse_contractor_data(self, text: str, fields_csv: str, context: str = "") -> dict:
        """Extract contractor fields from free-form text. Returns dict of field values."""
        prompt = (
            f"Extract the following fields from this contractor data: {fields_csv}\n"
            f"{context}\n\n"
            f"Input:\n{text}\n\n"
            "Return ONLY a JSON object with the extracted fields. "
            "Use empty string for fields not found in the input."
        )
        try:
            raw = self._call(prompt)
            return self._extract_json(raw)
        except Exception as e:
            logger.error("LLM parsing failed: %s", e)
            return {"parse_error": str(e)}

    def translate_name_to_russian(self, name_en: str) -> str:
        """Translate a name to Russian. Returns the translated name or empty string."""
        prompt = (
            f"Translate this person's name to Russian (Cyrillic): {name_en}\n\n"
            "Return ONLY the translated name, nothing else."
        )
        try:
            return self._call(prompt).strip().strip('"').strip("'")
        except Exception as e:
            logger.error("Name translation failed: %s", e)
            return ""

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
