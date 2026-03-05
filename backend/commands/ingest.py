"""Ingest articles — solid orchestration loop. LLM summarization in brain/dynamic."""

from __future__ import annotations

from datetime import datetime, timedelta

from common.config import EXPIRY_ARTICLE_SUMMARY_DAYS
from backend.domain.services.memory_service import MemoryService


class IngestArticles:

    def __init__(self, memory: MemoryService, gemini=None, retriever=None):
        self._memory = memory
        self._gemini = gemini
        self._retriever = retriever

    def execute(self, articles: list[dict], domain: str = "editorial",
                summarize_fn=None) -> list[str]:
        """Process articles. Returns list of entry UUIDs (created or updated).

        Each article dict should have at minimum: {title, url}.
        If 'content' is present and summarize_fn is provided, LLM summarization is used.
        Otherwise, the title is stored as-is.
        """
        fn = summarize_fn or self._legacy_summarize_fn()
        entry_ids = []
        for article in articles:
            if article.get("content") and fn:
                summary = fn(article)
            else:
                summary = article["title"]
            entry_id = self._memory.remember(
                text=summary,
                domain=domain,
                source="article_ingest",
                source_url=article.get("url") or None,
                tier="specific",
                expires_at=datetime.utcnow() + timedelta(days=EXPIRY_ARTICLE_SUMMARY_DAYS),
            )
            entry_ids.append(entry_id)
        return entry_ids

    def _legacy_summarize_fn(self):
        if not self._gemini:
            return None
        from common.prompt_loader import load_template

        def _summarize(article):
            retriever = self._retriever
            core = retriever.get_core() if retriever else ""
            prompt = load_template("knowledge/summarize-article.md", {
                "CORE_KNOWLEDGE": core,
                "TITLE": article["title"],
                "CONTENT": article["content"],
            })
            result = self._gemini.call(prompt)
            return result.get("summary", article["title"])
        return _summarize
