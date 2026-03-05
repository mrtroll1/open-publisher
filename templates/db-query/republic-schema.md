## Republic DB — схема (placeholder)

> TODO: заполнить реальной схемой после получения доступа к базе.
> Выполнить \dt и \d <table> для каждой релевантной таблицы.

Пример структуры (заменить на реальную):

### posts
- id (integer, PK)
- title (text)
- content (text)
- author_id (integer, FK → authors.id)
- published_at (timestamp)
- url (text)
- status (text)

### authors
- id (integer, PK)
- name (text)
- email (text)
