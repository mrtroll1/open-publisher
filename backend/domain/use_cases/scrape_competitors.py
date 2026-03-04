"""Scrape competitor websites, store observations in brain."""

from __future__ import annotations

from common.prompt_loader import load_template
from backend.domain.services.memory_service import MemoryService
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway


def _get_retriever():
    from backend.domain.services.knowledge_retriever import KnowledgeRetriever
    return KnowledgeRetriever()


class ScrapeCompetitors:

    def __init__(self, memory: MemoryService, gemini: GeminiGateway | None = None,
                 retriever=None):
        self._memory = memory
        self._gemini = gemini or GeminiGateway()
        self._retriever = retriever or _get_retriever()

    def execute(self, sources: list[dict]) -> list[str]:
        """Process competitor sources.
        Each source: {name: str, url: str, content: str}
        Returns list of entry UUIDs.
        """
        # Ensure the competitors domain exists
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

            summary = self._summarize(source)
            entry_id = self._memory.remember(
                text=summary,
                domain="competitors",
                source="competitor_scraper",
                source_url=source["url"],
                entity_id=entity_id,
                tier="specific",
            )
            entry_ids.append(entry_id)
        return entry_ids

    def _summarize(self, source: dict) -> str:
        core = self._retriever.get_core()
        prompt = load_template("knowledge/summarize-competitor.md", {
            "CORE_KNOWLEDGE": core,
            "NAME": source["name"],
            "URL": source["url"],
            "CONTENT": source["content"][:8000],
        })
        result = self._gemini.call(prompt)
        return result.get("summary", f"{source['name']}: {source['url']}")
