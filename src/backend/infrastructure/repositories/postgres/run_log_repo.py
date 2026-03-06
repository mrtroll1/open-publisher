"""Run log repository — stores LLM and tool call traces per run."""

from __future__ import annotations

import json

from backend.infrastructure.repositories.postgres.base import BasePostgresRepo


class RunLogRepo(BasePostgresRepo):

    def log_run_step(self, run_id: str, step: int, type: str, content: dict) -> str:
        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO run_logs (run_id, step, type, content)
                   VALUES (%s, %s, %s, %s)
                   RETURNING id""",
                (run_id, step, type, json.dumps(content, default=str)),
            )
            return str(cur.fetchone()[0])
