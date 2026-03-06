"""Ingest controller — article ingestion with LLM summarization."""

from __future__ import annotations

from backend.brain.base_controller import BaseController, PassThroughPreparer
from backend.brain.dynamic.summarize_article import SummarizeArticle
from backend.commands.ingest_articles import IngestUseCase
from backend.infrastructure.memory.memory_service import MemoryService


class IngestController(BaseController):
    def __init__(self, summarizer: SummarizeArticle, memory: MemoryService):
        super().__init__(PassThroughPreparer(), IngestUseCase(summarizer, memory))
