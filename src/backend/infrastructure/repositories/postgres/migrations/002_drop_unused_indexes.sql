-- 002_drop_unused_indexes.sql — Drop indexes not needed at current table sizes.
-- Keep only: idx_knowledge_embedding, idx_users_telegram_id,
--            idx_msg_telegram_mid, idx_msg_chat, idx_run_logs_run.

DROP INDEX IF EXISTS idx_knowledge_domain;
DROP INDEX IF EXISTS idx_knowledge_tier;
DROP INDEX IF EXISTS idx_knowledge_user;
DROP INDEX IF EXISTS idx_knowledge_source_url;
DROP INDEX IF EXISTS idx_knowledge_visibility;
DROP INDEX IF EXISTS idx_knowledge_env_id;
DROP INDEX IF EXISTS idx_users_email;
DROP INDEX IF EXISTS idx_users_role;
DROP INDEX IF EXISTS idx_msg_parent;
DROP INDEX IF EXISTS idx_msg_environment;
DROP INDEX IF EXISTS idx_msg_user;
DROP INDEX IF EXISTS idx_msg_email_mid;
