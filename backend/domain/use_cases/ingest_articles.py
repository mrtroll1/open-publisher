"""Fetch recent articles, summarize via LLM, store in brain."""

from __future__ import annotations

from common.prompt_loader import load_template
from backend.domain.services.memory_service import MemoryService
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway


class IngestArticles:

    def __init__(self, memory: MemoryService, gemini: GeminiGateway | None = None):
        self._memory = memory
        self._gemini = gemini or GeminiGateway()

    def execute(self, articles: list[dict], domain: str = "editorial") -> list[str]:
        """Process articles. Returns list of entry UUIDs (created or updated).

        Each article dict should have at minimum: {title, url}.
        If 'content' is present, LLM summarization is used.
        Otherwise, the title is stored as-is.
        """
        entry_ids = []
        for article in articles:
            if article.get("content"):
                summary = self._summarize(article)
            else:
                summary = article["title"]
            entry_id = self._memory.remember(
                text=summary,
                domain=domain,
                source="article_ingest",
                source_url=article.get("url", ""),
                tier="specific",
            )
            entry_ids.append(entry_id)
        return entry_ids

    def _summarize(self, article: dict) -> str:
        prompt = load_template("summarize-article.md", {
            "TITLE": article["title"],
            "CONTENT": article["content"][:8000],
        })
        result = self._gemini.call(prompt)
        return result.get("summary", article["title"])
