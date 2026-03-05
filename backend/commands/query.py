"""Query — SQL queries against Republic/Redefine databases via GenAI."""

from __future__ import annotations

from backend.brain.base_controller import BaseController, GenAIUseCase, PassThroughPreparer


def create_query_controller(query_db) -> BaseController:
    return BaseController(PassThroughPreparer(), GenAIUseCase(query_db))
