"""Scrape competitors — solid orchestration. LLM summarization in brain/dynamic."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from common.config import EXPIRY_COMPETITOR_SUMMARY_DAYS
from backend.domain.services.memory_service import MemoryService


class ScrapeCompetitors:

    def __init__(self, memory: MemoryService):
        self._memory = memory

    def execute(self, sources: list[dict],
                summarize_fn: Callable[[dict], str] | None = None) -> list[str]:
        """Process competitor sources.
        Each source: {name: str, url: str, content: str}
        Returns list of entry UUIDs.
        """
        self._memory.add_domain("competitors", "Наблюдения за конкурентами")
        entry_ids = []
        for source in sources:
            entity = self._memory.find_entity(query=source["name"])
            if not entity:
                entity_id = self._memory.add_entity(
                    kind="competitor", name=source["name"],
                )
            else:
                entity_id = entity["id"]

            if summarize_fn:
                summary = summarize_fn(source)
            else:
                summary = f"{source['name']}: {source['url']}"

            entry_id = self._memory.remember(
                text=summary,
                domain="competitors",
                source="competitor_scraper",
                source_url=source["url"],
                entity_id=entity_id,
                tier="specific",
                expires_at=datetime.utcnow() + timedelta(days=EXPIRY_COMPETITOR_SUMMARY_DAYS),
            )
            entry_ids.append(entry_id)
        return entry_ids
