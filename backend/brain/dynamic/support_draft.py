from __future__ import annotations

from backend.brain.base_genai import BaseGenAI
from backend.brain.dynamic.tech_support import TechSupport
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway


class SupportDraft(BaseGenAI):
    """Thin wrapper that delegates to TechSupport for inbox support handling."""

    def __init__(self, gemini: GeminiGateway, tech_support: TechSupport):
        super().__init__(gemini)
        self._tech_support = tech_support

    def run(self, input: str, context: dict, *, _depth: int = 0) -> dict:
        return self._tech_support.run(input, context, _depth=_depth)

    def _pick_template(self, input: str, context: dict) -> str:
        return self._tech_support._pick_template(input, context)

    def _build_context(self, input: str, context: dict) -> dict:
        return {}

    def _parse_response(self, raw: dict) -> dict:
        return self._tech_support._parse_response(raw)
