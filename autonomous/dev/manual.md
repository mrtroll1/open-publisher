# For Luka — Action Items & Setup Notes

> Things that require manual action or credentials that the autonomous agent cannot provide.

## Plan 6: Entities + Knowledge Extensions

### Manual verification after deploy
1. `/entity_add person "Иван Петров"` → should create entity
2. `/entity_link Иван Петров telegram_user_id=12345` → should link
3. `/entity_note Иван Петров Предпочитает оплату на карту` → should store linked knowledge
4. Send message as linked user → bot response should reflect entity context

## Plan 8: Active Knowledge Agents

### Manual verification after deploy
1. `/ingest_articles` → articles stored as knowledge entries
2. `/extract_knowledge 48` → facts extracted from recent conversations
3. Ask bot about recently ingested article content → should retrieve via RAG
4. Verify low-similarity RAG results are filtered out

