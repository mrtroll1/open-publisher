"""Email thread and decision repository."""

from __future__ import annotations

import re
import uuid

from backend.infrastructure.repositories.postgres.base import BasePostgresRepo
from common.models import IncomingEmail

_RE_PREFIX = re.compile(r"^(Re|Fwd|Fw)\s*:\s*", re.IGNORECASE)


def _normalize_subject(subject: str) -> str:
    s = subject.strip()
    while _RE_PREFIX.match(s):
        s = _RE_PREFIX.sub("", s, count=1).strip()
    return s.lower()


class EmailRepo(BasePostgresRepo):

    def find_thread(self, message_id: str, in_reply_to: str, subject: str) -> str:
        """Find existing thread or create a new one."""
        conn = self._get_conn()
        with conn.cursor() as cur:
            # Match by in_reply_to -> existing message_id
            if in_reply_to:
                cur.execute(
                    "SELECT thread_id FROM email_messages WHERE message_id = %s",
                    (in_reply_to,),
                )
                row = cur.fetchone()
                if row:
                    return row[0]

            # Match by normalized subject
            normalized = _normalize_subject(subject)
            if normalized:
                cur.execute(
                    "SELECT thread_id FROM email_threads WHERE normalized_subject = %s",
                    (normalized,),
                )
                row = cur.fetchone()
                if row:
                    return row[0]

            # Create new thread
            thread_id = uuid.uuid4().hex
            cur.execute(
                "INSERT INTO email_threads (thread_id, subject, normalized_subject) VALUES (%s, %s, %s)",
                (thread_id, subject, normalized),
            )
            return thread_id

    def save_message(self, thread_id: str, email: IncomingEmail, direction: str) -> None:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO email_messages
                   (thread_id, message_id, in_reply_to, from_addr, to_addr,
                    subject, body, date, direction)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (message_id) DO NOTHING""",
                (
                    thread_id,
                    email.message_id,
                    email.in_reply_to,
                    email.from_addr,
                    email.to_addr,
                    email.subject,
                    email.body,
                    email.date,
                    direction,
                ),
            )

    def get_thread_history(self, thread_id: str, limit: int = 10) -> list[dict]:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """SELECT message_id, from_addr, to_addr, subject, body, date, direction
                   FROM email_messages
                   WHERE thread_id = %s
                   ORDER BY created_at ASC
                   LIMIT %s""",
                (thread_id, limit),
            )
            cols = ["message_id", "from_addr", "to_addr", "subject", "body", "date", "direction"]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def create_email_decision(self, task: str, channel: str, input_message_ids: list[str], output: str = "") -> str:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO email_decisions (task, channel, input_message_ids, output)
                   VALUES (%s, %s, %s, %s)
                   RETURNING id""",
                (task, channel, input_message_ids, output),
            )
            return str(cur.fetchone()[0])

    def update_email_decision(self, decision_id: str, status: str, decided_by: str | None = None) -> None:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE email_decisions
                   SET status = %s, decided_by = %s, decided_at = NOW()
                   WHERE id = %s""",
                (status, decided_by or "", decision_id),
            )

    def update_email_decision_output(self, decision_id: str, output: str) -> None:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE email_decisions SET output = %s WHERE id = %s",
                (output, decision_id),
            )

    def get_email_decision(self, decision_id: str) -> dict | None:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, created_at, task, channel, input_message_ids,
                          output, status, decided_by, decided_at
                   FROM email_decisions WHERE id = %s""",
                (decision_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = ["id", "created_at", "task", "channel", "input_message_ids",
                    "output", "status", "decided_by", "decided_at"]
            result = dict(zip(cols, row))
            result["id"] = str(result["id"])
            return result

    def get_thread_message_ids(self, thread_id: str) -> list[str]:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """SELECT message_id FROM email_messages
                   WHERE thread_id = %s
                   ORDER BY created_at ASC""",
                (thread_id,),
            )
            return [row[0] for row in cur.fetchall()]
