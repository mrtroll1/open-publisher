-- 013: web_scrape tool permission — admin only by default.

INSERT INTO tool_permissions (tool_name, environment, allowed_roles) VALUES
    ('web_scrape', '*', ARRAY['admin'])
ON CONFLICT DO NOTHING;
