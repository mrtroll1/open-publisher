-- 012: Task dependency chain — each task can depend on one predecessor.

ALTER TABLE tasks ADD COLUMN IF NOT EXISTS depends_on UUID REFERENCES tasks(id);

CREATE INDEX IF NOT EXISTS idx_tasks_depends_on ON tasks(depends_on)
    WHERE depends_on IS NOT NULL;
