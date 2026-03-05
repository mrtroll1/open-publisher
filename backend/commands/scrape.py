"""Scrape competitors — solid orchestration. LLM summarization in brain/dynamic."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from common.config import EXPIRY_COMPETITOR_SUMMARY_DAYS
from backend.domain.services.memory_service import MemoryService


class ScrapeCompetitors:

    def __init__(self, memory: MemoryService, gemini=None, retriever=None):
        self._memory = memory
        self._gemini = gemini
        self._retriever = retriever

    def execute(self, sources: list[dict],
                summarize_fn: Callable[[dict], str] | None = None) -> list[str]:
        """Process competitor sources.
        Each source: {name: str, url: str, content: str}
        Returns list of entry UUIDs.
        """
        fn = summarize_fn or self._legacy_summarize_fn()
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

            if fn:
                summary = fn(source)
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

    def _legacy_summarize_fn(self):
        if not self._gemini:
            return None
        from common.prompt_loader import load_template

        def _summarize(source):
            retriever = self._retriever
            core = retriever.get_core() if retriever else ""
            prompt = load_template("knowledge/summarize-competitor.md", {
                "CORE_KNOWLEDGE": core,
                "NAME": source["name"],
                "URL": source["url"],
                "CONTENT": source["content"],
            })
            result = self._gemini.call(prompt)
            return result.get("summary", f"{source['name']}: {source['url']}")
        return _summarize
