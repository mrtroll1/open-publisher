-- 001_initial.sql — Clean schema, current state of all tables.
-- This replaces the monolithic _SCHEMA_SQL that accumulated migration cruft.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS knowledge_domains (
    name TEXT PRIMARY KEY,
    description TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS units_of_knowledge (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tier TEXT NOT NULL DEFAULT 'specific',
    domain TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'seed',
    embedding vector(256),
    is_active BOOLEAN DEFAULT TRUE,
    user_id UUID,
    source_url TEXT,
    expires_at TIMESTAMP,
    parent_id UUID REFERENCES units_of_knowledge(id),
    visibility TEXT NOT NULL DEFAULT 'public',
    environment_id TEXT,
    source_type TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_knowledge_embedding
    ON units_of_knowledge USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);

CREATE TABLE IF NOT EXISTS environments (
    name         TEXT PRIMARY KEY,
    description  TEXT NOT NULL DEFAULT '',
    system_context TEXT NOT NULL DEFAULT '',
    allowed_domains TEXT[],
    created_at   TIMESTAMP DEFAULT NOW(),
    updated_at   TIMESTAMP DEFAULT NOW()
);

-- FK after environments exists
ALTER TABLE units_of_knowledge
    ADD CONSTRAINT fk_uok_environment FOREIGN KEY (environment_id) REFERENCES environments(name);

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

-- FK after users exists
ALTER TABLE units_of_knowledge
    ADD CONSTRAINT fk_uok_user FOREIGN KEY (user_id) REFERENCES users(id);

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
CREATE INDEX IF NOT EXISTS idx_msg_telegram_mid ON messages((metadata->>'telegram_message_id')) WHERE metadata->>'telegram_message_id' IS NOT NULL;

CREATE TABLE IF NOT EXISTS run_logs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id      UUID NOT NULL,
    step        INTEGER NOT NULL DEFAULT 0,
    type        TEXT NOT NULL,
    content     JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_run_logs_run ON run_logs(run_id, step);

-- Seed default environments
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
