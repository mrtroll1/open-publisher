-- 011: Collapse admin_dm, contractor_dm, editor_dm, user_dm into a single "dm" environment.
-- Role-based system prompt is handled in code; permissions use roles, not environments.

-- Create unified dm environment
INSERT INTO environments (name, description, system_context)
VALUES ('dm', 'Личный чат', '')
ON CONFLICT (name) DO NOTHING;

-- Migrate tool permissions to dm (role-based)
DELETE FROM tool_permissions WHERE environment IN ('admin_dm', 'contractor_dm', 'editor_dm', 'user_dm');
INSERT INTO tool_permissions (tool_name, environment, allowed_roles) VALUES
  ('support', 'dm', '{admin,editor}'),
  ('contractors', 'dm', '{admin,editor}'),
  ('goals', 'dm', '{admin}')
ON CONFLICT (tool_name, environment) DO UPDATE SET allowed_roles = EXCLUDED.allowed_roles;

-- Rebind all DM chats
UPDATE environment_bindings SET environment = 'dm'
WHERE environment IN ('admin_dm', 'contractor_dm', 'editor_dm', 'user_dm');

-- Migrate knowledge entries
UPDATE units_of_knowledge SET environment_id = 'dm'
WHERE environment_id IN ('admin_dm', 'contractor_dm', 'editor_dm', 'user_dm');

-- Migrate messages
UPDATE messages SET environment = 'dm'
WHERE environment IN ('admin_dm', 'contractor_dm', 'editor_dm', 'user_dm');

-- Remove old DM environments
DELETE FROM environments WHERE name IN ('admin_dm', 'contractor_dm', 'editor_dm', 'user_dm');
