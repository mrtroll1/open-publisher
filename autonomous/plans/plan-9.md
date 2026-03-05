# Phase 9: DB Query Tool — Natural Language to SQL

> Instead of hardcoded commands for data retrieval, Gemini generates and executes
> read-only SQL queries against Republic and Redefine production databases.
> Combined with existing RAG, this gives the bot structured + semantic data access.
>
> Flow: request → classify → ToolRouter picks tools → parallel execution
> (RAG + SQL queries) → aggregated context → final Gemini reply.

## 9.0 Pre-flight

- [ ] 9.0.1 Luka: create read-only postgres users on Republic and Redefine DBs
- [ ] 9.0.2 Luka: set up SSH key access for tunneling to both DB servers
- [ ] 9.0.3 Luka: provide table schemas (or access to inspect them) for both DBs
- [ ] 9.0.4 Add env vars to `config/.env` (see external-todo.md for full list)
- [ ] 9.0.5 Add `sshtunnel` to requirements

---

## 9.1 SSH Tunnel + Read-Only DB Gateway

- [ ] 9.1.1 Add config vars to `common/config.py`:
  - `REPUBLIC_DB_*` (SSH_HOST, SSH_USER, SSH_KEY_PATH, DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS)
  - `REDEFINE_DB_*` (same set)
- [ ] 9.1.2 Create `backend/infrastructure/gateways/query_gateway.py`:
  - `QueryGateway(ssh_host, ssh_user, ssh_key, db_host, db_port, db_name, db_user, db_pass)`
  - Opens SSH tunnel via `sshtunnel` on init, connects psycopg2 to forwarded port
  - `execute(sql, params) -> list[dict]` — runs a SELECT, returns rows as dicts
  - App-level guard: reject anything that isn't a SELECT (defense in depth, DB user is already read-only)
  - Tunnel and connection are lazy-initialized, kept alive, reconnect on failure
- [ ] 9.1.3 Tests: mock sshtunnel + psycopg2, verify SELECT-only guard, verify reconnect

---

## 9.2 Query Tool (NL → SQL → results)

- [ ] 9.2.1 Create `templates/db-query/compose-query.md`:
  - Input: schema description, user question, example queries
  - Output: `{"sql": "SELECT ...", "explanation": "..."}`
  - Instruct: only SELECT, no CTEs with side effects, use explicit column names
- [ ] 9.2.2 Create `templates/db-query/republic-schema.md`:
  - Table names, columns, types, relationships, sample data descriptions
  - Luka fills in actual schema after 9.0.3
- [ ] 9.2.3 Create `templates/db-query/redefine-schema.md`:
  - Same structure, Luka fills in
- [ ] 9.2.4 Create `backend/domain/services/query_tool.py`:
  - `QueryTool(gateway: QueryGateway, schema_template: str, gemini: GeminiGateway)`
  - `query(question: str) -> dict` — calls Gemini with schema + question, executes SQL, returns `{"rows": [...], "sql": "...", "explanation": "..."}`
  - Row limit (e.g. 50) to avoid blowing up context
  - Catches DB errors, returns them as explanation (no retry with different SQL for now)
- [ ] 9.2.5 Add `compose_request.compose_query()` to compose_request.py
- [ ] 9.2.6 Tests: mock Gemini + gateway, verify SQL execution, row limiting, error handling

---

## 9.3 Tool Router (decides which tools to use)

- [ ] 9.3.1 Create `templates/chat/require-tools.md`:
  - Input: user question, available tools with descriptions
  - Output: `{"tools": [{"name": "rag", "query": "..."}, {"name": "republic_db", "query": "..."}, ...]}`
  - Tools: `rag` (semantic search), `republic_db` (Republic SQL), `redefine_db` (Redefine SQL)
  - Examples: "сегодняшние статьи" → republic_db; "что такое Republic" → rag; "подписка пользователя X" → redefine_db + rag
- [ ] 9.3.2 Create `backend/domain/services/tool_router.py`:
  - `ToolRouter(gemini: GeminiGateway)`
  - `route(question: str) -> list[ToolCall]` — returns which tools to invoke and with what sub-queries
- [ ] 9.3.3 Tests: mock Gemini, verify routing for various query types

---

## 9.4 Wire into conversation flow

- [ ] 9.4.1 Update `backend/wiring.py`: factory functions for QueryGateway + QueryTool (republic, redefine)
- [ ] 9.4.2 Update `backend/domain/services/conversation_service.py`:
  - `generate_nl_reply` gains new flow:
    1. ToolRouter decides tools
    2. Execute selected tools in parallel (RAG + SQL queries)
    3. Aggregate results into knowledge_context
    4. Existing conversation_reply call with enriched context
  - Graceful degradation: if SSH tunnel is down or query fails, fall back to RAG-only
- [ ] 9.4.3 Update `_handle_nl_reply` in conversation_handlers.py if needed
- [ ] 9.4.4 Tests: integration test of the full flow with mocked tools

---

## 9.5 Verification & hardcoded command cleanup

- [ ] 9.5.1 Manual test: `/nl про что сегодняшние статьи?` → should return today's articles
- [ ] 9.5.2 Manual test: `/nl какая подписка у user@example.com?` → should query Redefine
- [ ] 9.5.3 Manual test: `/nl сколько статей вышло на этой неделе?` → should query Republic
- [ ] 9.5.4 Evaluate which existing commands can be retired (lookup, articles, etc.)
- [ ] 9.5.5 If retiring commands: update `_ADMIN_NL_DESCRIPTIONS`, router, replies
