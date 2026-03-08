"""Search — retrieve from knowledge base."""

from __future__ import annotations

from typing import Any

from backend.brain.base_controller import BaseUseCase
from backend.infrastructure.memory.retriever import KnowledgeRetriever


class SearchUseCase(BaseUseCase):
    def __init__(self, retriever: KnowledgeRetriever):
        self._retriever = retriever

    def execute(self, prepared: Any, env: dict, user: dict) -> Any:
        role = user.get("role", "user") if user else "user"
        user_id = user.get("id") if user else None
        env_name = env.get("name")
        return {"results": self._retriever.retrieve(
            prepared, role=role, user_id=user_id, environment=env_name,
        )}
