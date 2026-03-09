-- 004: Add last_summarized_at and telegram_handle to environments.
ALTER TABLE environments ADD COLUMN IF NOT EXISTS last_summarized_at TIMESTAMP DEFAULT '2025-01-01';
ALTER TABLE environments ADD COLUMN IF NOT EXISTS telegram_handle TEXT;
