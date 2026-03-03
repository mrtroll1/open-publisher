"""Code task repository."""

from __future__ import annotations

from backend.infrastructure.repositories.postgres.base import BasePostgresRepo


class CodeTaskRepo(BasePostgresRepo):

    def create_code_task(self, requested_by: str, input_text: str, output_text: str, verbose: bool = False) -> str:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO code_tasks (requested_by, input_text, output_text, is_verbose)
                   VALUES (%s, %s, %s, %s)
                   RETURNING id""",
                (requested_by, input_text, output_text, verbose),
            )
            return str(cur.fetchone()[0])

    def rate_code_task(self, task_id: str, rating: int) -> None:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE code_tasks SET rating = %s, rated_at = NOW() WHERE id = %s",
                (rating, task_id),
            )
