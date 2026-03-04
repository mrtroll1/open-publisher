"""Extract memorable facts from recent conversations, store in brain."""

from __future__ import annotations

from datetime import datetime, timedelta

from common.config import EXPIRY_CONVERSATION_FACTS_DAYS
from common.prompt_loader import load_template
from backend.domain.services.memory_service import MemoryService
from backend.infrastructure.repositories.postgres import DbGateway
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway


def _get_retriever():
    from backend.domain.services.knowledge_retriever import KnowledgeRetriever
    return KnowledgeRetriever()


class ExtractConversationKnowledge:

    def __init__(self, memory: MemoryService, db: DbGateway,
                 gemini: GeminiGateway | None = None, retriever=None):
        self._memory = memory
        self._db = db
        self._gemini = gemini or GeminiGateway()
        self._retriever = retriever or _get_retriever()

    def execute(self, chat_id: int) -> list[str]:
        """Extract knowledge from unprocessed conversations in a chat.
        Returns list of new entry UUIDs."""
        messages = self._db.get_unextracted_conversations(chat_id)
        if len(messages) < 3:
            return []

        conversation_ids = [str(m["id"]) for m in messages]
        transcript = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
        facts = self._extract_facts(transcript)

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

    def _extract_facts(self, transcript: str) -> list[dict]:
        core = self._retriever.get_core()
        existing = self._retriever.retrieve(transcript, limit=10)
        existing_text = existing if existing else "Нет известных фактов."
        prompt = load_template("knowledge/extract-facts.md", {
            "CORE_KNOWLEDGE": core,
            "EXISTING_KNOWLEDGE": existing_text,
            "TRANSCRIPT": transcript,
        })
        result = self._gemini.call(prompt)
        return result.get("facts", [])
