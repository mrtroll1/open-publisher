"""Ingest articles — summarize and store in knowledge base."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from backend.brain.base_controller import BaseUseCase
from backend.brain.dynamic.summarize_article import SummarizeArticle
from backend.config import EXPIRY_ARTICLE_SUMMARY_DAYS
from backend.infrastructure.memory.memory_service import MemoryService


class IngestUseCase(BaseUseCase):
    def __init__(self, summarizer: SummarizeArticle, memory: MemoryService):
        self._summarizer = summarizer
        self._memory = memory

    def execute(self, prepared: Any, _env: dict, _user: dict) -> list[str]:
        entry_ids = []
        for article in prepared:
            if article.get("content"):
                result = self._summarizer.run(
                    article["content"], {"title": article.get("title", "")},
                )
                summary = result.get("summary", article.get("title", ""))
            else:
                summary = article["title"]

            entry_id = self._memory.remember(
                text=summary,
                domain="editorial",
                source="article_ingest",
                source_url=article.get("url") or None,
                tier="specific",
                expires_at=datetime.utcnow() + timedelta(days=EXPIRY_ARTICLE_SUMMARY_DAYS),
            )
            entry_ids.append(entry_id)
        return entry_ids
