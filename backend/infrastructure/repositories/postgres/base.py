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

-- Migrate: core entries in non-identity domains → meta
UPDATE knowledge_entries SET tier = 'meta'
WHERE tier = 'core' AND domain != 'identity';

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

-- Migrate: add knowledge_extracted_at (existing rows get NOW so they're skipped; new rows get NULL)
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS knowledge_extracted_at TIMESTAMP DEFAULT NOW();
ALTER TABLE conversations ALTER COLUMN knowledge_extracted_at DROP DEFAULT;
CREATE INDEX IF NOT EXISTS idx_conv_unextracted ON conversations(chat_id, knowledge_extracted_at) WHERE knowledge_extracted_at IS NULL;

CREATE TABLE IF NOT EXISTS environments (
    name         TEXT PRIMARY KEY,
    description  TEXT NOT NULL DEFAULT '',
    system_context TEXT NOT NULL DEFAULT '',
    allowed_domains TEXT[],
    created_at   TIMESTAMP DEFAULT NOW(),
    updated_at   TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS environment_bindings (
    chat_id      BIGINT PRIMARY KEY,
    environment  TEXT NOT NULL REFERENCES environments(name),
    created_at   TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS entities (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind          TEXT NOT NULL,
    name          TEXT NOT NULL,
    external_ids  JSONB DEFAULT '{}',
    summary       TEXT NOT NULL DEFAULT '',
    embedding     vector(256),
    created_at    TIMESTAMP DEFAULT NOW(),
    updated_at    TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_entity_kind ON entities(kind);
CREATE INDEX IF NOT EXISTS idx_entity_external_ids ON entities USING GIN(external_ids);
CREATE INDEX IF NOT EXISTS idx_entity_name ON entities(name);

-- Entity FK on knowledge_entries
DO $$ BEGIN
    ALTER TABLE knowledge_entries ADD COLUMN entity_id UUID REFERENCES entities(id);
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_knowledge_entity
    ON knowledge_entries(entity_id) WHERE entity_id IS NOT NULL;

DO $$ BEGIN
    ALTER TABLE knowledge_entries ADD COLUMN source_url TEXT;
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_knowledge_source_url
    ON knowledge_entries(source_url) WHERE source_url IS NOT NULL;

DO $$ BEGIN
    ALTER TABLE knowledge_entries ADD COLUMN expires_at TIMESTAMP;
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE knowledge_entries ADD COLUMN parent_id UUID REFERENCES knowledge_entries(id);
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

INSERT INTO environments (name, description, system_context, allowed_domains) VALUES
  ('admin_dm', 'Приватный чат с администратором Republic',
   'Это приватный чат с администратором. Полный доступ ко всем функциям. Можно обсуждать внутренние вопросы, контрагентов, бюджет. Давай развёрнутые ответы.',
   NULL),
  ('editorial_group', 'Групповой чат редакции Republic',
   'Это групповой чат редакции. Видят все сотрудники. Отвечай кратко и по делу. Не раскрывай персональные данные контрагентов.',
   ARRAY['tech_support', 'editorial', 'identity']),
  ('contractor_dm', 'Личный чат с контрагентом Republic',
   'Это личный чат с контрагентом Republic. Будь вежлив и формален. Помогай с документами, оплатой, регистрацией.',
   ARRAY['contractor', 'payments']),
  ('email', 'Обработка входящей почты',
   'Ты составляешь ответ на email. Пиши формально и грамотно.',
   ARRAY['tech_support'])
ON CONFLICT (name) DO NOTHING;
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
        self._seed_bindings()

    def _seed_bindings(self):
        from common.config import ADMIN_TELEGRAM_IDS

        conn = self._get_conn()
        with conn.cursor() as cur:
            for admin_id in ADMIN_TELEGRAM_IDS:
                cur.execute(
                    "INSERT INTO environment_bindings (chat_id, environment) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (admin_id, "admin_dm"),
                )

    def close(self):
        if self._conn and not self._conn.closed:
            self._conn.close()
            self._conn = None
