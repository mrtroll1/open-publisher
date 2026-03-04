"""Scheduled knowledge pipeline runner."""

from __future__ import annotations

from backend.domain.services.memory_service import MemoryService
from backend.infrastructure.repositories.postgres import DbGateway
from backend.domain.use_cases.extract_conversation_knowledge import ExtractConversationKnowledge


def run_scheduled_pipelines(memory: MemoryService, db: DbGateway) -> None:
    """Run all scheduled knowledge pipelines. Called periodically."""
    extractor = ExtractConversationKnowledge(memory, db)
    environments = db.list_environments()
    for env in environments:
        bindings = db.get_bindings_for_environment(env["name"])
        for chat_id in bindings:
            extractor.execute(chat_id, since_hours=24)
