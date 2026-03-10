"""Scrape Telegram channels and produce daily digests."""

from __future__ import annotations

import logging
from datetime import date, datetime

from backend.brain.prompt_loader import load_template
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from backend.infrastructure.memory.memory_service import MemoryService
from backend.infrastructure.memory.retriever import KnowledgeRetriever
from backend.infrastructure.repositories.postgres import DbGateway

logger = logging.getLogger(__name__)


def _format_messages(messages: list[dict]) -> str:
    lines = []
    for m in messages:
        sender = m.get("sender", "channel")
        dt = m.get("date", "")
        text = m.get("text", "").strip()
        if text:
            lines.append(f"[{dt}] {sender}: {text}")
    return "\n".join(lines)


class ScrapeChannels:
    def __init__(self, gemini: GeminiGateway, memory: MemoryService, db: DbGateway,
                 retriever: KnowledgeRetriever | None = None):
        self._gemini = gemini
        self._memory = memory
        self._db = db
        self._retriever = retriever

    def process_channel(self, messages: list[dict], environment: str) -> dict:
        """Process fetched messages into a single daily digest per channel."""
        env = self._db.get_environment(environment)
        if not env:
            return {"count": 0, "error": f"Environment {environment} not found"}

        if not messages:
            return {"count": 0}

        channel = env.get("telegram_handle", environment)
        env_context = env.get("system_context", "")
        knowledge = self._retriever.get_core() if self._retriever else ""
        today = date.today().isoformat()
        domain = environment

        formatted = _format_messages(messages)
        prompt = load_template("knowledge/scrape-tg-channel.md", {
            "KNOWLEDGE": knowledge or "(нет)",
            "CHANNEL": channel,
            "ENVIRONMENT": env_context or "(не указан)",
            "DATE": today,
            "MESSAGES": formatted,
        })

        try:
            result = self._gemini.call(prompt)
        except Exception:
            logger.exception("Failed to generate digest for %s", channel)
            return {"count": 0}

        digest = result.get("digest", "")
        if not digest:
            return {"count": 0}

        self._db.get_or_create_domain(domain)
        source_url = f"tg://{channel}/digest/{today}"

        self._memory.remember(
            digest, domain,
            source=environment, tier="specific",
            visibility="role:editor",
            environment_id=environment,
            source_type="tg_channel",
            source_url=source_url,
        )

        self._db.update_environment(environment, last_summarized_at=datetime.utcnow())
        return {"count": 1}
