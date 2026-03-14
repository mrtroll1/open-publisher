-- 010: user_dm environment + restrict support tool permissions.

-- Create user_dm environment
INSERT INTO environments (name, description)
VALUES ('user_dm', 'Личный чат с пользователем бота')
ON CONFLICT (name) DO NOTHING;

-- Fix support tool: remove global wildcard, add per-environment grants
DELETE FROM tool_permissions WHERE tool_name = 'support' AND environment = '*';
INSERT INTO tool_permissions (tool_name, environment, allowed_roles)
VALUES
  ('support', 'admin_dm', '{*}'),
  ('support', 'contractor_dm', '{*}'),
  ('support', 'editor_dm', '{*}'),
  ('support', 'editorial_group', '{*}'),
  ('support', 'ceo_group', '{*}')
ON CONFLICT (tool_name, environment) DO UPDATE SET allowed_roles = EXCLUDED.allowed_roles;
