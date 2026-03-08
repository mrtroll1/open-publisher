-- 003_drop_parent_id.sql — Remove unused parent_id from units_of_knowledge.
ALTER TABLE units_of_knowledge DROP COLUMN IF EXISTS parent_id;
