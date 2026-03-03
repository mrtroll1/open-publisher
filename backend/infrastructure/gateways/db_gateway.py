"""Database gateway — Postgres for email thread tracking."""

from __future__ import annotations

import json
import logging
import re
import uuid

import psycopg2

from common.config import DATABASE_URL
from common.models import IncomingEmail

logger = logging.getLogger(__name__)

_SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

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

CREATE TABLE IF NOT EXISTS knowledge_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tier TEXT NOT NULL DEFAULT 'domain',
    scope TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'seed',
    embedding vector(256),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_knowledge_embedding
    ON knowledge_entries USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);
CREATE INDEX IF NOT EXISTS idx_knowledge_scope
    ON knowledge_entries(scope, is_active);
CREATE INDEX IF NOT EXISTS idx_knowledge_tier
    ON knowledge_entries(tier, is_active);

CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    reply_to_id UUID REFERENCES conversations(id),
    message_id BIGINT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_conv_chat ON conversations(chat_id, created_at);
CREATE INDEX IF NOT EXISTS idx_conv_msg ON conversations(chat_id, message_id);
CREATE INDEX IF NOT EXISTS idx_conv_reply ON conversations(reply_to_id);
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

    # --- knowledge_entries ---

    def save_knowledge_entry(self, tier: str, scope: str, title: str, content: str, source: str, embedding: list[float] | None = None) -> str:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO knowledge_entries (tier, scope, title, content, source, embedding)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (tier, scope, title, content, source, str(embedding) if embedding is not None else None),
            )
            return str(cur.fetchone()[0])

    def update_knowledge_entry(self, entry_id: str, content: str, embedding: list[float] | None = None) -> bool:
        """Update a knowledge entry. Returns True if an entry was actually updated."""
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE knowledge_entries
                   SET content = %s, embedding = %s, updated_at = NOW()
                   WHERE id = %s""",
                (content, str(embedding) if embedding is not None else None, entry_id),
            )
            return cur.rowcount > 0

    def search_knowledge(self, query_embedding: list[float], scope: str | None = None, limit: int = 5) -> list[dict]:
        conn = self._get_conn()
        emb_str = str(query_embedding)
        with conn.cursor() as cur:
            if scope is not None:
                cur.execute(
                    """SELECT id, tier, scope, title, content, source,
                              1 - (embedding <=> %s::vector) AS similarity
                       FROM knowledge_entries
                       WHERE is_active = TRUE AND scope = %s
                       ORDER BY embedding <=> %s::vector ASC
                       LIMIT %s""",
                    (emb_str, scope, emb_str, limit),
                )
            else:
                cur.execute(
                    """SELECT id, tier, scope, title, content, source,
                              1 - (embedding <=> %s::vector) AS similarity
                       FROM knowledge_entries
                       WHERE is_active = TRUE
                       ORDER BY embedding <=> %s::vector ASC
                       LIMIT %s""",
                    (emb_str, emb_str, limit),
                )
            cols = ["id", "tier", "scope", "title", "content", "source", "similarity"]
            rows = []
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                d["id"] = str(d["id"])
                rows.append(d)
            return rows

    def get_knowledge_by_tier(self, tier: str) -> list[dict]:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, tier, scope, title, content, source
                   FROM knowledge_entries
                   WHERE tier = %s AND is_active = TRUE
                   ORDER BY scope, created_at""",
                (tier,),
            )
            cols = ["id", "tier", "scope", "title", "content", "source"]
            rows = []
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                d["id"] = str(d["id"])
                rows.append(d)
            return rows

    def get_knowledge_by_scope(self, scope: str) -> list[dict]:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, tier, scope, title, content, source
                   FROM knowledge_entries
                   WHERE scope = %s AND is_active = TRUE
                   ORDER BY created_at""",
                (scope,),
            )
            cols = ["id", "tier", "scope", "title", "content", "source"]
            rows = []
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                d["id"] = str(d["id"])
                rows.append(d)
            return rows

    def list_knowledge(self, scope: str | None = None, tier: str | None = None) -> list[dict]:
        conn = self._get_conn()
        with conn.cursor() as cur:
            sql = """SELECT id, tier, scope, title, source, created_at
                     FROM knowledge_entries
                     WHERE is_active = TRUE"""
            params: list = []
            if scope is not None:
                sql += " AND scope = %s"
                params.append(scope)
            if tier is not None:
                sql += " AND tier = %s"
                params.append(tier)
            sql += " ORDER BY tier, scope, created_at"
            cur.execute(sql, tuple(params))
            cols = ["id", "tier", "scope", "title", "source", "created_at"]
            rows = []
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                d["id"] = str(d["id"])
                rows.append(d)
            return rows

    def deactivate_knowledge(self, entry_id: str) -> bool:
        """Soft-delete a knowledge entry. Returns True if an entry was actually deactivated."""
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE knowledge_entries SET is_active = FALSE, updated_at = NOW() WHERE id = %s",
                (entry_id,),
            )
            return cur.rowcount > 0

    # --- conversations ---

    def save_conversation(self, chat_id: int, user_id: int, role: str, content: str,
                          reply_to_id: str | None = None, message_id: int | None = None,
                          metadata: dict | None = None) -> str:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO conversations
                   (chat_id, user_id, role, content, reply_to_id, message_id, metadata)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (chat_id, user_id, role, content, reply_to_id, message_id,
                 json.dumps(metadata or {})),
            )
            return str(cur.fetchone()[0])

    def get_conversation_by_message_id(self, chat_id: int, message_id: int) -> dict | None:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM conversations WHERE chat_id = %s AND message_id = %s",
                (chat_id, message_id),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [desc[0] for desc in cur.description]
            result = dict(zip(cols, row))
            result["id"] = str(result["id"])
            if result.get("reply_to_id"):
                result["reply_to_id"] = str(result["reply_to_id"])
            return result

    def get_reply_chain(self, conversation_id: str, depth: int = 10) -> list[dict]:
        conn = self._get_conn()
        chain: list[dict] = []
        current_id = conversation_id
        with conn.cursor() as cur:
            for _ in range(depth):
                cur.execute("SELECT * FROM conversations WHERE id = %s", (current_id,))
                row = cur.fetchone()
                if not row:
                    break
                cols = [desc[0] for desc in cur.description]
                rec = dict(zip(cols, row))
                rec["id"] = str(rec["id"])
                if rec.get("reply_to_id"):
                    rec["reply_to_id"] = str(rec["reply_to_id"])
                chain.append(rec)
                if not rec.get("reply_to_id"):
                    break
                current_id = rec["reply_to_id"]
        chain.reverse()
        return chain

    def close(self):
        if self._conn and not self._conn.closed:
            self._conn.close()
            self._conn = None
