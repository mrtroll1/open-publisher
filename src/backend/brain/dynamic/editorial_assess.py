from __future__ import annotations

from backend.brain.base_genai import BaseGenAI
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from backend.infrastructure.memory.retriever import KnowledgeRetriever


class EditorialAssess(BaseGenAI):

    def __init__(self, gemini: GeminiGateway, retriever: KnowledgeRetriever):
        super().__init__(gemini)
        self._model = "gemini-3-flash-preview"
        self._retriever = retriever

    def _pick_template(self, input: str, context: dict) -> str:
        return "email/editorial-assess.md"

    def _build_context(self, input: str, context: dict) -> dict:
        core = self._retriever.get_core()
        return {
            "CORE_KNOWLEDGE": core,
            "EMAIL": input,
        }

    def _parse_response(self, raw: dict) -> dict:
        return {
            "forward": raw.get("forward", False),
            "reply": raw.get("reply", ""),
        }
