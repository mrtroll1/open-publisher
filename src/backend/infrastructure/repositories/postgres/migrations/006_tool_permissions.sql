-- 006: Move tool permissions from code to DB.

CREATE TABLE IF NOT EXISTS tool_permissions (
    tool_name    TEXT NOT NULL,
    environment  TEXT NOT NULL DEFAULT '*',
    allowed_roles TEXT[] NOT NULL DEFAULT ARRAY['admin'],
    PRIMARY KEY (tool_name, environment)
);

-- Seed current hardcoded permissions.
INSERT INTO tool_permissions (tool_name, environment, allowed_roles) VALUES
    -- health & support: everyone everywhere
    ('health',          '*',               ARRAY['*']),
    ('support',         '*',               ARRAY['*']),
    -- admin-only by default, open in editorial & ceo groups
    ('search',          '*',               ARRAY['admin']),
    ('search',          'editorial_group', ARRAY['*']),
    ('search',          'ceo_group',       ARRAY['*']),
    ('teach',           '*',               ARRAY['admin']),
    ('teach',           'editorial_group', ARRAY['*']),
    ('teach',           'ceo_group',       ARRAY['*']),
    ('yandex_metrica',  '*',               ARRAY['admin']),
    ('yandex_metrica',  'editorial_group', ARRAY['*']),
    ('yandex_metrica',  'ceo_group',       ARRAY['*']),
    ('cloudflare',      '*',               ARRAY['admin']),
    ('cloudflare',      'editorial_group', ARRAY['*']),
    ('cloudflare',      'ceo_group',       ARRAY['*']),
    ('republic_db',     '*',               ARRAY['admin']),
    ('republic_db',     'editorial_group', ARRAY['*']),
    ('republic_db',     'ceo_group',       ARRAY['*']),
    ('redefine_db',     '*',               ARRAY['admin']),
    ('redefine_db',     'editorial_group', ARRAY['*']),
    ('redefine_db',     'ceo_group',       ARRAY['*']),
    ('agent_db',        '*',               ARRAY['admin']),
    ('agent_db',        'editorial_group', ARRAY['*']),
    ('agent_db',        'ceo_group',       ARRAY['*']),
    -- admin + ceo only
    ('budget',          '*',               ARRAY['admin']),
    ('budget',          'ceo_group',       ARRAY['*']),
    ('invoice',         '*',               ARRAY['admin']),
    ('invoice',         'ceo_group',       ARRAY['*']),
    ('code',            '*',               ARRAY['admin']),
    ('code',            'ceo_group',       ARRAY['*']),
    ('user',            '*',               ARRAY['admin']),
    ('user',            'ceo_group',       ARRAY['*']),
    -- permissions management: admin only
    ('permissions',     '*',               ARRAY['admin'])
ON CONFLICT DO NOTHING;
