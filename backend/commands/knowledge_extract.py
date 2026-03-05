"""Knowledge extraction — solid orchestration. LLM extraction in brain/dynamic."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Callable

from common.config import EXPIRY_CONVERSATION_FACTS_DAYS
from backend.domain.services.memory_service import MemoryService
from backend.infrastructure.repositories.postgres import DbGateway

logger = logging.getLogger(__name__)


class ExtractConversationKnowledge:

    def __init__(self, memory: MemoryService, db: DbGateway):
        self._memory = memory
        self._db = db

    def execute(self, chat_id: int, extract_fn: Callable[[str], list[dict]] | None = None) -> list[str]:
        """Extract knowledge from unprocessed conversations in a chat.
        Returns list of new entry UUIDs.

        extract_fn: optional LLM-based fact extractor (transcript -> list[dict]).
        """
        messages = self._db.get_unextracted_conversations(chat_id)
        if len(messages) < 3:
            return []

        conversation_ids = [str(m["id"]) for m in messages]
        transcript = "\n".join(f"{m['role']}: {m['content']}" for m in messages)

        if not extract_fn:
            return []

        facts = extract_fn(transcript)

        entry_ids = []
        for fact in facts:
            domain = fact.get("domain", "general")
            permanent = fact.get("permanent", False)
            expires_at = None if permanent else (datetime.utcnow() + timedelta(days=EXPIRY_CONVERSATION_FACTS_DAYS))
            entry_id = self._memory.remember(
                text=fact["text"],
                domain=domain,
                source="conversation_extract",
                tier="specific",
                expires_at=expires_at,
            )
            entry_ids.append(entry_id)

        self._db.mark_conversations_extracted(conversation_ids)
        return entry_ids


def run_scheduled_pipelines(memory: MemoryService, db: DbGateway,
                            extract_fn: Callable[[str], list[dict]] | None = None) -> None:
    """Run all scheduled knowledge pipelines. Called periodically."""
    extractor = ExtractConversationKnowledge(memory, db)
    environments = db.list_environments()
    for env in environments:
        bindings = db.get_bindings_for_environment(env["name"])
        for chat_id in bindings:
            try:
                extractor.execute(chat_id, extract_fn=extract_fn)
            except Exception:
                logger.exception("Pipeline extraction failed for chat %s in env %s",
                                 chat_id, env["name"])
