"""Extract memorable facts from recent conversations, store in brain."""

from __future__ import annotations

from common.prompt_loader import load_template
from backend.domain.services.memory_service import MemoryService
from backend.infrastructure.repositories.postgres import DbGateway
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway


class ExtractConversationKnowledge:

    def __init__(self, memory: MemoryService, db: DbGateway,
                 gemini: GeminiGateway | None = None):
        self._memory = memory
        self._db = db
        self._gemini = gemini or GeminiGateway()

    def execute(self, chat_id: int, since_hours: int = 24) -> list[str]:
        """Extract knowledge from recent conversations in a chat.
        Returns list of new entry UUIDs."""
        messages = self._db.get_recent_conversations(chat_id, hours=since_hours)
        if len(messages) < 3:
            return []

        transcript = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
        facts = self._extract_facts(transcript)

        entry_ids = []
        for fact in facts:
            domain = fact.get("domain", "general")
            entry_id = self._memory.remember(
                text=fact["text"],
                domain=domain,
                source="conversation_extract",
                tier="specific",
            )
            entry_ids.append(entry_id)
        return entry_ids

    def _extract_facts(self, transcript: str) -> list[dict]:
        prompt = load_template("extract-facts.md", {"TRANSCRIPT": transcript})
        result = self._gemini.call(prompt)
        return result.get("facts", [])
