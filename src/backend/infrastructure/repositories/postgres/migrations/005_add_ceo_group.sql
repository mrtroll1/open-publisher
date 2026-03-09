-- 005: Add ceo_group environment, drop legacy allowed_domains column.

INSERT INTO environments (name, description, system_context)
VALUES (
    'ceo_group',
    'Групповой чат директоров Republic и Redefine',
    'Это групповой чат команды директоров. Полный доступ ко всем функциям. Отвечай кратко и по делу.'
)
ON CONFLICT (name) DO NOTHING;

ALTER TABLE environments DROP COLUMN IF EXISTS allowed_domains;
