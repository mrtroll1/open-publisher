from __future__ import annotations

from backend.brain.prompt_loader import load_template
from backend.config import GEMINI_MODEL_FAST
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway


class RecursionLimitError(Exception):
    pass


class BaseGenAI:
    MAX_DEPTH = 5

    def __init__(self, gemini: GeminiGateway):
        self._gemini = gemini
        self._model = GEMINI_MODEL_FAST

    def run(self, input: str, context: dict, *, _depth: int = 0) -> dict:
        if _depth >= self.MAX_DEPTH:
            raise RecursionLimitError(f"Recursion depth {_depth} exceeds limit {self.MAX_DEPTH}")
        template = self._pick_template(input, context)
        built_context = self._build_context(input, context)
        prompt = load_template(template, built_context)
        raw = self._call_ai(prompt)
        return self._parse_response(raw)

    def _pick_template(self, input: str, context: dict) -> str:
        raise NotImplementedError

    def _build_context(self, input: str, context: dict) -> dict:
        raise NotImplementedError

    def _call_ai(self, prompt: str) -> dict:
        return self._gemini.call(prompt, self._model)

    def _parse_response(self, raw: dict) -> dict:
        raise NotImplementedError
