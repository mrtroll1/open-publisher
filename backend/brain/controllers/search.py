"""Search controller — knowledge base retrieval."""

from __future__ import annotations

from backend.brain.base_controller import BaseController, PassThroughPreparer
from backend.commands.search import SearchUseCase
from backend.infrastructure.memory.retriever import KnowledgeRetriever


class SearchController(BaseController):
    def __init__(self, retriever: KnowledgeRetriever):
        super().__init__(PassThroughPreparer(), SearchUseCase(retriever))
