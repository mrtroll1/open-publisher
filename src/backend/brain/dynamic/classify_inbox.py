from __future__ import annotations

from backend.brain.base_genai import BaseGenAI
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from backend.infrastructure.memory.retriever import KnowledgeRetriever


class ClassifyInbox(BaseGenAI):

    def __init__(self, gemini: GeminiGateway, retriever: KnowledgeRetriever):
        super().__init__(gemini)
        self._retriever = retriever

    def _pick_template(self, input: str, context: dict) -> str:
        return "email/inbox-classify.md"

    def _build_context(self, input: str, context: dict) -> dict:
        core = self._retriever.get_core()
        return {
            "CORE_KNOWLEDGE": core,
            "EMAIL": input,
        }

    def _parse_response(self, raw: dict) -> dict:
        return {
            "category": raw.get("category", "ignore"),
            "reason": raw.get("reason", ""),
        }
