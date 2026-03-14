-- 009: Add web_search tool permissions.

INSERT INTO tool_permissions (tool_name, environment, allowed_roles) VALUES
    ('web_search', '*', ARRAY['*'])
ON CONFLICT DO NOTHING;
