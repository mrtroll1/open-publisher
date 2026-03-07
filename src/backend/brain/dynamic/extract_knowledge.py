from __future__ import annotations

from backend.brain.base_genai import BaseGenAI
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from backend.infrastructure.memory.retriever import KnowledgeRetriever


class ExtractKnowledge(BaseGenAI):

    def __init__(self, gemini: GeminiGateway, retriever: KnowledgeRetriever):
        super().__init__(gemini)
        self._retriever = retriever

    def _pick_template(self, _input: str, _context: dict) -> str:
        return "knowledge/extract-facts.md"

    def _build_context(self, input: str, _context: dict) -> dict:
        core = self._retriever.get_core()
        existing = self._retriever.retrieve(input, limit=10)
        return {
            "CORE_KNOWLEDGE": core,
            "EXISTING_KNOWLEDGE": existing or "Нет известных фактов.",
            "TRANSCRIPT": input,
        }

    def _parse_response(self, raw: dict) -> dict:
        return {"facts": raw.get("facts", [])}
