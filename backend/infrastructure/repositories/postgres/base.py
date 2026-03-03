"""Base Postgres repository — connection handling and schema init."""

from __future__ import annotations

import psycopg2

from common.config import DATABASE_URL

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

CREATE TABLE IF NOT EXISTS knowledge_domains (
    name TEXT PRIMARY KEY,
    description TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS knowledge_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tier TEXT NOT NULL DEFAULT 'specific',
    domain TEXT NOT NULL,
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
CREATE INDEX IF NOT EXISTS idx_knowledge_domain
    ON knowledge_entries(domain, is_active);
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


class BasePostgresRepo:

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

    def close(self):
        if self._conn and not self._conn.closed:
            self._conn.close()
            self._conn = None
