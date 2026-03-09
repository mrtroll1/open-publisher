"""Scrape Telegram channels and extract knowledge."""

from __future__ import annotations

import logging
from datetime import datetime

from backend.brain.prompt_loader import load_template
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from backend.infrastructure.memory.memory_service import MemoryService
from backend.infrastructure.memory.retriever import KnowledgeRetriever
from backend.infrastructure.repositories.postgres import DbGateway

logger = logging.getLogger(__name__)

CHUNK_SIZE = 50


def _format_messages(messages: list[dict]) -> str:
    lines = []
    for m in messages:
        sender = m.get("sender", "channel")
        date = m.get("date", "")
        text = m.get("text", "").strip()
        if text:
            lines.append(f"[{date}] {sender}: {text}")
    return "\n".join(lines)


class ScrapeChannels:
    def __init__(self, gemini: GeminiGateway, memory: MemoryService, db: DbGateway,
                 retriever: KnowledgeRetriever | None = None):
        self._gemini = gemini
        self._memory = memory
        self._db = db
        self._retriever = retriever

    def process_channel(self, messages: list[dict], environment: str) -> dict:
        """Process fetched messages for a single channel environment."""
        env = self._db.get_environment(environment)
        if not env:
            return {"count": 0, "error": f"Environment {environment} not found"}

        env_context = env.get("system_context", "")
        channel = env.get("telegram_handle", environment)
        domains = self._db.list_domains()
        domain_names = ", ".join(d["name"] for d in domains) if domains else "(пусто)"
        knowledge = self._retriever.get_core() if self._retriever else ""

        if not messages:
            return {"count": 0}

        chunks = [messages[i:i + CHUNK_SIZE] for i in range(0, len(messages), CHUNK_SIZE)]
        total_stored = 0

        for chunk in chunks:
            entries = self._extract_from_chunk(chunk, env_context, channel, domain_names, knowledge)
            total_stored += self._store_entries(entries, environment)

        self._db.update_environment(environment, last_summarized_at=datetime.utcnow())
        return {"count": total_stored}

    def _extract_from_chunk(self, chunk: list[dict], env_context: str,
                            channel: str, domain_names: str,
                            knowledge: str = "") -> list[dict]:
        formatted = _format_messages(chunk)
        prompt = load_template("knowledge/scrape-tg-channel.md", {
            "KNOWLEDGE": knowledge or "(нет)",
            "CHANNEL": channel,
            "ENVIRONMENT": env_context or "(не указан)",
            "DOMAINS": domain_names,
            "MESSAGES": formatted,
        })
        try:
            result = self._gemini.call(prompt)
            return result.get("entries", [])
        except Exception:
            logger.exception("Failed to extract knowledge from channel chunk")
            return []

    def _store_entries(self, entries: list[dict], environment: str) -> int:
        stored = 0
        for entry in entries:
            domain = entry.get("domain", "competitor_intel")
            content = entry.get("content", "")
            if not content:
                continue
            self._db.get_or_create_domain(domain)
            self._memory.remember(
                content, domain,
                source="competitor_tg_channel", tier="specific",
                visibility=entry.get("visibility", "role:editor"),
                environment_id=environment,
                source_type="competitor_tg_channel",
            )
            stored += 1
        return stored
