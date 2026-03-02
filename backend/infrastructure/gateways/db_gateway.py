"""Database gateway — Postgres for email thread tracking."""

from __future__ import annotations

import logging
import re
import uuid

import psycopg2

from common.config import DATABASE_URL
from common.models import IncomingEmail

logger = logging.getLogger(__name__)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS email_threads (
    thread_id TEXT PRIMARY KEY,
    subject TEXT,
    normalized_subject TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS email_messages (
    id SERIAL PRIMARY KEY,
    thread_id TEXT REFERENCES email_threads(thread_id),
    message_id TEXT UNIQUE,
    in_reply_to TEXT,
    from_addr TEXT,
    to_addr TEXT,
    subject TEXT,
    body TEXT,
    date TEXT,
    direction TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS email_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMP DEFAULT NOW(),
    task TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'EMAIL',
    input_message_ids TEXT[] NOT NULL,
    output TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'PENDING',
    decided_by TEXT DEFAULT '',
    decided_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS llm_classifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMP DEFAULT NOW(),
    task TEXT NOT NULL,
    model TEXT NOT NULL,
    input_text TEXT NOT NULL,
    output_json TEXT NOT NULL,
    latency_ms INT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS payment_validations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMP DEFAULT NOW(),
    contractor_id TEXT,
    contractor_type TEXT,
    input_text TEXT NOT NULL,
    parsed_json TEXT NOT NULL,
    validation_warnings TEXT[],
    is_final BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS code_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMP DEFAULT NOW(),
    requested_by TEXT,
    input_text TEXT NOT NULL,
    output_text TEXT NOT NULL,
    is_verbose BOOLEAN DEFAULT FALSE,
    rating INT,
    rated_at TIMESTAMP
);
"""

_RE_PREFIX = re.compile(r"^(Re|Fwd|Fw)\s*:\s*", re.IGNORECASE)


def _normalize_subject(subject: str) -> str:
    s = subject.strip()
    while _RE_PREFIX.match(s):
        s = _RE_PREFIX.sub("", s, count=1).strip()
    return s.lower()


class DbGateway:

    def __init__(self):
        self._conn = None

    def _get_conn(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(DATABASE_URL)
            self._conn.autocommit = True
        return self._conn

    def init_schema(self):
        with self._get_conn().cursor() as cur:
            cur.execute(_SCHEMA_SQL)

    def find_thread(self, message_id: str, in_reply_to: str, subject: str) -> str:
        """Find existing thread or create a new one."""
        conn = self._get_conn()
        with conn.cursor() as cur:
            # Match by in_reply_to → existing message_id
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

    def log_classification(self, task: str, model: str, input_text: str, output_json: str, latency_ms: int) -> None:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO llm_classifications (task, model, input_text, output_json, latency_ms)
                   VALUES (%s, %s, %s, %s, %s)""",
                (task, model, input_text, output_json, latency_ms),
            )

    def log_payment_validation(
        self, contractor_id: str, contractor_type: str,
        input_text: str, parsed_json: str,
        warnings: list[str] | None = None, is_final: bool = False,
    ) -> str:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO payment_validations
                   (contractor_id, contractor_type, input_text, parsed_json, validation_warnings, is_final)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (contractor_id, contractor_type, input_text, parsed_json, warnings or [], is_final),
            )
            return str(cur.fetchone()[0])

    def finalize_payment_validation(self, validation_id: str) -> None:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE payment_validations SET is_final = TRUE WHERE id = %s",
                (validation_id,),
            )

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

    def close(self):
        if self._conn and not self._conn.closed:
            self._conn.close()
            self._conn = None
