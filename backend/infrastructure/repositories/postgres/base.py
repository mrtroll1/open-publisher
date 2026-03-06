"""Base Postgres repository — connection handling and schema init."""

from __future__ import annotations

import psycopg2

from common.config import DATABASE_URL

_SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

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

CREATE TABLE IF NOT EXISTS users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          TEXT NOT NULL DEFAULT '',
    role          TEXT NOT NULL DEFAULT 'user',
    telegram_id   BIGINT UNIQUE,
    email         TEXT UNIQUE,
    created_at    TIMESTAMP DEFAULT NOW(),
    updated_at    TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id) WHERE telegram_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email) WHERE email IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);

CREATE TABLE IF NOT EXISTS messages (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    text          TEXT NOT NULL DEFAULT '',
    embedding     vector(256),
    environment   TEXT REFERENCES environments(name),
    chat_id       BIGINT,
    type          TEXT NOT NULL DEFAULT 'user',
    user_id       UUID REFERENCES users(id),
    parent_id     UUID REFERENCES messages(id),
    created_at    TIMESTAMP DEFAULT NOW(),
    metadata      JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_msg_chat ON messages(chat_id, created_at) WHERE chat_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_msg_parent ON messages(parent_id) WHERE parent_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_msg_environment ON messages(environment, created_at) WHERE environment IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_msg_user ON messages(user_id) WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_msg_telegram_mid ON messages((metadata->>'telegram_message_id')) WHERE metadata->>'telegram_message_id' IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_msg_email_mid ON messages((metadata->>'email_message_id')) WHERE metadata->>'email_message_id' IS NOT NULL;

-- user FK on knowledge_entries
DO $$ BEGIN
    ALTER TABLE knowledge_entries ADD COLUMN user_id UUID REFERENCES users(id);
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_knowledge_user
    ON knowledge_entries(user_id) WHERE user_id IS NOT NULL;

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
                cur.execute(
                    "INSERT INTO users (name, role, telegram_id) VALUES (%s, %s, %s) "
                    "ON CONFLICT (telegram_id) DO UPDATE SET role = 'admin'",
                    ("admin", "admin", admin_id),
                )

    def close(self):
        if self._conn and not self._conn.closed:
            self._conn.close()
            self._conn = None
