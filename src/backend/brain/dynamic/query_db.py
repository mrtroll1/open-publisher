from __future__ import annotations

import logging

from backend.brain.base_genai import BaseGenAI
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from backend.infrastructure.gateways.query_gateway import LocalQueryGateway, QueryGateway
from backend.infrastructure.repositories.postgres import DbGateway

logger = logging.getLogger(__name__)

_MAX_ROWS = 50


class QueryDB(BaseGenAI):
    """Compose SQL from natural language, execute, return rows.

    Used as a conversational tool by the Brain's ReAct loop.
    Schema knowledge is fetched from the knowledge DB (domain=infra).
    """

    def __init__(self, gemini: GeminiGateway, gateway: QueryGateway | LocalQueryGateway,
                 db: DbGateway, schema_domain: str = "databases"):
        super().__init__(gemini)
        self._model = "gemini-2.5-flash"
        self._gateway = gateway
        self._db = db
        self._schema_domain = schema_domain

    @property
    def available(self) -> bool:
        return self._gateway.available

    def _pick_template(self, input: str, context: dict) -> str:
        return "db-query/compose-query.md"

    def _build_context(self, input: str, context: dict) -> dict:
        entries = self._db.get_knowledge_by_domain(self._schema_domain)
        schema = "\n\n".join(e["content"] for e in entries) if entries else "(schema not available)"
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
