# For Luka — Action Items & Setup Notes

> Things that require manual action or credentials that the autonomous agent cannot provide.

## Plan 5: Environments + Prompt Pipeline

### Manual verification after deploy
1. Send @mention in editorial group → bot reply should use `editorial_group` system_context (verify via response tone — should be brief, no PII)
2. `/env` in admin DM → should show all 4 environments with descriptions and bound chat_ids
3. `/env_bind editorial_group` in a new group chat → should bind that chat

## Plan 6: Entities + Knowledge Extensions

### Manual verification after deploy
1. `/entity_add person "Иван Петров"` → should create entity
2. `/entity_link Иван Петров telegram_user_id=12345` → should link
3. `/entity_note Иван Петров Предпочитает оплату на карту` → should store linked knowledge
4. Send message as linked user → bot response should reflect entity context

## Plan 7: Memory API + MCP Interface

### MCP Server setup
1. Install `mcp` package: `pip install 'mcp>=1.0,<3'`
2. Test MCP server locally: `python -m mcp_server` (requires DATABASE_URL + GEMINI_API_KEY)
3. Configure Claude Code: copy `claude_mcp_config.json` to `~/.claude/` and update paths/credentials
4. Test round-trip: use `remember` + `recall` tools in Claude to verify

## Plan 8: Active Knowledge Agents

### Manual verification after deploy
1. `/ingest_articles` → articles stored as knowledge entries
2. `/extract_knowledge 48` → facts extracted from recent conversations
3. Ask bot about recently ingested article content → should retrieve via RAG
4. Verify low-similarity RAG results are filtered out

