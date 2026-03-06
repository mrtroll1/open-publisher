"""Query controller — SQL queries via GenAI."""

from __future__ import annotations

from backend.brain.base_controller import BaseController, GenAIUseCase, PassThroughPreparer


class QueryController(BaseController):
    def __init__(self, query_db):
        super().__init__(PassThroughPreparer(), GenAIUseCase(query_db))
