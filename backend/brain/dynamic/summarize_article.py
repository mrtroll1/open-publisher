from __future__ import annotations

from backend.brain.base_genai import BaseGenAI
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from backend.infrastructure.memory.retriever import KnowledgeRetriever


class SummarizeArticle(BaseGenAI):

    def __init__(self, gemini: GeminiGateway, retriever: KnowledgeRetriever):
        super().__init__(gemini)
        self._retriever = retriever

    def _pick_template(self, input: str, context: dict) -> str:
        return "knowledge/summarize-article.md"

    def _build_context(self, input: str, context: dict) -> dict:
        core = self._retriever.get_core()
        return {
            "CORE_KNOWLEDGE": core,
            "TITLE": context.get("title", ""),
            "CONTENT": input,
        }

    def _parse_response(self, raw: dict) -> dict:
        return {"summary": raw.get("summary", "")}
