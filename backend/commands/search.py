"""Search — retrieve from knowledge base."""

from __future__ import annotations

from typing import Any

from backend.brain.base_controller import BaseUseCase
from backend.infrastructure.memory.retriever import KnowledgeRetriever


class SearchUseCase(BaseUseCase):
    def __init__(self, retriever: KnowledgeRetriever):
        self._retriever = retriever

    def execute(self, prepared: Any, env: dict, user: dict) -> Any:
        domains = env.get("allowed_domains")
        return {"results": self._retriever.retrieve(prepared, domains=domains)}


