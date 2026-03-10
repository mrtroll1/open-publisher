-- 007: Goals, tasks, progress, and notifications.

CREATE TABLE IF NOT EXISTS goals (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title       TEXT NOT NULL,
    description TEXT,
    status      TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'paused', 'done', 'abandoned')),
    priority    INT NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
    deadline    TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tasks (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    goal_id           UUID REFERENCES goals(id) ON DELETE SET NULL,
    title             TEXT NOT NULL,
    description       TEXT,
    status            TEXT NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'in_progress', 'done', 'blocked')),
    trigger_condition TEXT,
    due_date          TIMESTAMPTZ,
    assigned_to       TEXT NOT NULL DEFAULT 'user'
                      CHECK (assigned_to IN ('user', 'agent')),
    result            TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at      TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS goal_progress (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    goal_id    UUID NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    note       TEXT NOT NULL,
    source     TEXT NOT NULL DEFAULT 'user'
               CHECK (source IN ('user', 'agent', 'auto')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS notifications (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type       TEXT NOT NULL,
    payload    JSONB NOT NULL DEFAULT '{}',
    read       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_goals_status ON goals(status);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_goal_id ON tasks(goal_id);
CREATE INDEX IF NOT EXISTS idx_tasks_trigger ON tasks(trigger_condition)
    WHERE trigger_condition IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_notifications_unread ON notifications(read)
    WHERE read = FALSE;

-- Tool permissions: admin only, in relevant environments.
INSERT INTO tool_permissions (tool_name, environment, allowed_roles) VALUES
    ('goals', '*',               ARRAY['admin']),
    ('goals', 'admin_dm',        ARRAY['admin']),
    ('goals', 'editorial_group', ARRAY['admin']),
    ('goals', 'ceo_group',       ARRAY['admin'])
ON CONFLICT DO NOTHING;
