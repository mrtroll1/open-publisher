from __future__ import annotations

import logging

from common.prompt_loader import load_template
from backend.brain.base_genai import BaseGenAI
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from backend.infrastructure.gateways.query_gateway import QueryGateway

logger = logging.getLogger(__name__)

_MAX_ROWS = 50


class QueryDB(BaseGenAI):
    """Compose SQL from natural language, execute, return rows.

    Used as a tool by ConversationReply — not a standalone route.
    """

    def __init__(self, gemini: GeminiGateway, gateway: QueryGateway,
                 schema_template: str):
        super().__init__(gemini)
        self._model = "gemini-2.5-flash"
        self._gateway = gateway
        self._schema_template = schema_template

    @property
    def available(self) -> bool:
        return self._gateway.available

    def _pick_template(self, input: str, context: dict) -> str:
        return "db-query/compose-query.md"

    def _build_context(self, input: str, context: dict) -> dict:
        schema = load_template(self._schema_template)
        return {
            "SCHEMA": schema,
            "QUESTION": input,
        }

    def _parse_response(self, raw: dict) -> dict:
        sql = raw.get("sql", "")
        explanation = raw.get("explanation", "")

        if not sql:
            return {"rows": [], "sql": "", "explanation": explanation,
                    "error": "LLM did not produce a query"}

        try:
            rows = self._gateway.execute(sql)
            if len(rows) > _MAX_ROWS:
                rows = rows[:_MAX_ROWS]
            return {"rows": rows, "sql": sql, "explanation": explanation, "error": ""}
        except Exception as e:
            logger.warning("Query execution failed: %s | SQL: %s", e, sql)
            return {"rows": [], "sql": sql, "explanation": explanation, "error": str(e)}
