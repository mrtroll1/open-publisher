"""LLM classification logging repository."""

from __future__ import annotations

from backend.infrastructure.repositories.postgres.base import BasePostgresRepo


class ClassificationRepo(BasePostgresRepo):

    def log_classification(self, task: str, model: str, input_text: str, output_json: str, latency_ms: int) -> None:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO llm_classifications (task, model, input_text, output_json, latency_ms)
                   VALUES (%s, %s, %s, %s, %s)""",
                (task, model, input_text, output_json, latency_ms),
            )
