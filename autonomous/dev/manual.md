# For Luka — Action Items & Setup Notes

> Things that require manual action or credentials that the autonomous agent cannot provide.

## Plan 6: Entities + Knowledge Extensions

### Manual verification after deploy
1. `/entity_add person "Иван Петров"` → should create entity
2. `/entity_link Иван Петров telegram_user_id=12345` → should link
3. `/entity_note Иван Петров Предпочитает оплату на карту` → should store linked knowledge
4. Send message as linked user → bot response should reflect entity context

## Plan 9: DB Query Tool

### Prerequisites (do these first)
1. Create read-only postgres users on Republic and Redefine servers (see `external-todo.md`)
2. Set up SSH key access for tunneling
3. Add env vars to `config/.env`
4. Provide DB schemas (`\dt` + `\d <table>` output for both DBs)
5. Add `sshtunnel` to requirements: `pip install sshtunnel`

### Manual verification after deploy
1. `/nl про что сегодняшние статьи?` → should query Republic DB + return article info
2. `/nl какая подписка у user@example.com?` → should query Redefine DB
3. `/nl сколько статей вышло на этой неделе?` → should query Republic DB with date filter
4. `/nl что такое Republic?` → should use RAG (no DB query needed)
5. Verify failed SSH tunnel → graceful fallback to RAG-only

