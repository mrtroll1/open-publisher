"""Knowledge extraction — solid orchestration. LLM extraction in brain/dynamic."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Callable

from common.config import EXPIRY_CONVERSATION_FACTS_DAYS
from backend.infrastructure.memory.memory_service import MemoryService
from backend.infrastructure.repositories.postgres import DbGateway

logger = logging.getLogger(__name__)


class ExtractConversationKnowledge:

    def __init__(self, memory: MemoryService, db: DbGateway, gemini=None, retriever=None):
        self._memory = memory
        self._db = db
        self._gemini = gemini
        self._retriever = retriever

    def execute(self, chat_id: int, extract_fn: Callable[[str], list[dict]] | None = None) -> list[str]:
        """Extract knowledge from unprocessed conversations in a chat.
        Returns list of new entry UUIDs.

        extract_fn: optional LLM-based fact extractor (transcript -> list[dict]).
        """
        fn = extract_fn or self._legacy_extract_fn()

        messages = self._db.get_unextracted_conversations(chat_id)
        if len(messages) < 3:
            return []

        conversation_ids = [str(m["id"]) for m in messages]
        transcript = "\n".join(f"{m['role']}: {m['content']}" for m in messages)

        if not fn:
            return []

        facts = fn(transcript)

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

    def _legacy_extract_fn(self):
        if not self._gemini:
            return None
        from common.prompt_loader import load_template

        def _extract(transcript):
            retriever = self._retriever
            core = retriever.get_core() if retriever else ""
            existing = retriever.retrieve(transcript, limit=10) if retriever else ""
            existing_text = existing if existing else "Нет известных фактов."
            prompt = load_template("knowledge/extract-facts.md", {
                "CORE_KNOWLEDGE": core,
                "EXISTING_KNOWLEDGE": existing_text,
                "TRANSCRIPT": transcript,
            })
            result = self._gemini.call(prompt)
            return result.get("facts", [])
        return _extract


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
