"""QueryTool — natural language to SQL via Gemini, executed against a read-only DB."""

from __future__ import annotations

import logging

from common.prompt_loader import load_template
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from backend.infrastructure.gateways.query_gateway import QueryGateway

logger = logging.getLogger(__name__)

_MAX_ROWS = 50


class QueryTool:

    def __init__(self, gateway: QueryGateway, schema_template: str,
                 gemini: GeminiGateway | None = None):
        self._gateway = gateway
        self._schema_template = schema_template
        self._gemini = gemini or GeminiGateway()

    @property
    def available(self) -> bool:
        return self._gateway.available

    def query(self, question: str) -> dict:
        """Translate question to SQL, execute, return results.

        Returns {"rows": [...], "sql": "...", "explanation": "...", "error": "..."}.
        """
        schema = load_template(self._schema_template)
        prompt = load_template("db-query/compose-query.md", {
            "SCHEMA": schema,
            "QUESTION": question,
        })
        result = self._gemini.call(prompt)
        sql = result.get("sql", "")
        explanation = result.get("explanation", "")

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
