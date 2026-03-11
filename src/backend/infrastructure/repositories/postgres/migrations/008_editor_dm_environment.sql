-- 008: editor_dm environment and contractors tool permissions.

INSERT INTO environments (name, description, system_context) VALUES
  ('editor_dm', 'Личный чат с редактором Republic',
   'Это личный чат с редактором. Помогай с управлением документами для выплат, контрагентами, редиректами, ставками. Отвечай по-русски, кратко.')
ON CONFLICT (name) DO NOTHING;

INSERT INTO tool_permissions (tool_name, environment, allowed_roles) VALUES
    ('contractors', 'editor_dm',  ARRAY['admin', 'editor']),
    ('contractors', 'admin_dm',   ARRAY['admin', 'editor']),
    ('contractors', '*',          ARRAY['admin'])
ON CONFLICT DO NOTHING;
