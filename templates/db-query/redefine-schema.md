## Redefine DB — схема (placeholder)

> TODO: заполнить реальной схемой после получения доступа к базе.
> Выполнить \dt и \d <table> для каждой релевантной таблицы.

Пример структуры (заменить на реальную):

### customers
- id (integer, PK)
- email (text)
- name (text)
- created_at (timestamp)

### subscriptions
- id (integer, PK)
- customer_id (integer, FK → customers.id)
- plan (text)
- status (text)
- started_at (timestamp)
- expires_at (timestamp)

### payments
- id (integer, PK)
- customer_id (integer, FK → customers.id)
- amount (numeric)
- currency (text)
- created_at (timestamp)
- status (text)
