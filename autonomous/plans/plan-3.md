# Plan 3 — Agent Memory, Knowledge DB, Conversation Persistence & Learning

## Current State

- **Knowledge**: Static `.md` files in `knowledge/` — loaded into prompts via `load_knowledge()`. Updating requires code change + deploy.
- **Templates**: Static `.md` files in `templates/` — prompt structure, output format. Engineering artifacts.
- **DB**: PostgreSQL (`pgvector/pgvector:pg16` image) with 6 tables: `email_threads`, `email_messages`, `email_decisions`, `llm_classifications`, `code_tasks`, `payment_validations`. **pgvector extension NOT enabled.**
- **Conversations**: Telegram interactions are stateless. Email threads tracked but not Telegram chats.
- **Learning**: Zero feedback loops. Code ratings stored but never read. No way to teach the bot at runtime.
- **Embeddings**: `google-genai` installed (supports `text-embedding-004`), but no embedding code exists.

## Architecture: Knowledge Hierarchy

Three tiers of knowledge, all in PostgreSQL:

| Tier | Purpose | Loading | Examples |
|---|---|---|---|
| **core** | Always loaded into every prompt. Identity, key rules, guidelines. | Full scope load (`WHERE tier = 'core'`) | Who is Luka, what is Republic, communication style |
| **domain** | Loaded when relevant via semantic search. FAQ, procedures, learned insights. | Embedding similarity (`<=>` operator) | How to reset password, refund policy, CMS procedures |
| **conversation** | Historical context. Not injected into prompts directly — retrieved when continuing a conversation. | Reply chain lookup | Past Telegram dialogs, email thread history |

**Core entries** are stored as readable markdown in the DB (`content` field). Editable via Telegram (`/knowledge edit <id>`). Small count (~5-10 entries). Always injected. This replaces `knowledge/base.md` and key parts of `tech-support.md`.

**Domain entries** grow over time as the bot learns from admin feedback, teaching, and conversations. Retrieved by embedding similarity when composing prompts.

**Templates stay as files.** They define prompt structure (JSON output format, persona instructions, placeholder layout) — these are code, not knowledge.

---

## Phase 1: Embeddings Infrastructure

### 1.1 Enable pgvector extension

- [x] Add `CREATE EXTENSION IF NOT EXISTS vector;` to `_SCHEMA_SQL` in `db_gateway.py`, before table definitions

**Files**: `backend/infrastructure/gateways/db_gateway.py`

### 1.2 Create embedding gateway

- [x] Create `backend/infrastructure/gateways/embedding_gateway.py`:
  ```python
  class EmbeddingGateway:
      def embed_texts(self, texts: list[str]) -> list[list[float]]: ...
      def embed_one(self, text: str) -> list[float]: ...
  ```
- [x] Use `google-genai` client with `text-embedding-004`, 256 dimensions
- [x] The `google-genai` package is already in `requirements.txt` — no new dependency

**Files**: `backend/infrastructure/gateways/embedding_gateway.py` (new)

### 1.3 Tests

- [x] Create `tests/test_embedding_gateway.py` — mock the genai client, verify correct API call format and dimension config
- [x] Run tests to confirm

---

## Phase 2: Knowledge Store

### 2.1 New table: `knowledge_entries`

- [ ] Add to `_SCHEMA_SQL` in `db_gateway.py`:
  ```sql
  CREATE TABLE IF NOT EXISTS knowledge_entries (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      tier TEXT NOT NULL DEFAULT 'domain',   -- 'core' | 'domain'
      scope TEXT NOT NULL,                    -- 'identity', 'tech_support', 'email_inbox', etc.
      title TEXT NOT NULL DEFAULT '',
      content TEXT NOT NULL,                  -- stored as markdown
      source TEXT NOT NULL DEFAULT 'seed',    -- 'seed' | 'admin_feedback' | 'admin_teach'
      embedding vector(256),
      is_active BOOLEAN DEFAULT TRUE,
      created_at TIMESTAMP DEFAULT NOW(),
      updated_at TIMESTAMP DEFAULT NOW()
  );
  CREATE INDEX IF NOT EXISTS idx_knowledge_embedding
      ON knowledge_entries USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);
  CREATE INDEX IF NOT EXISTS idx_knowledge_scope
      ON knowledge_entries(scope, is_active);
  CREATE INDEX IF NOT EXISTS idx_knowledge_tier
      ON knowledge_entries(tier, is_active);
  ```

### 2.2 DbGateway methods

- [ ] `save_knowledge_entry(tier, scope, title, content, source, embedding) -> str`
- [ ] `update_knowledge_entry(entry_id, content, embedding) -> None`
- [ ] `search_knowledge(query_embedding, scope=None, limit=5) -> list[dict]` — cosine similarity, only `is_active=TRUE`
- [ ] `get_knowledge_by_tier(tier) -> list[dict]` — load all core entries
- [ ] `get_knowledge_by_scope(scope) -> list[dict]` — load full scope
- [ ] `list_knowledge(scope=None, tier=None) -> list[dict]` — for admin listing
- [ ] `deactivate_knowledge(entry_id) -> None` — soft delete

**Files**: `backend/infrastructure/gateways/db_gateway.py`

### 2.3 Knowledge retriever

- [ ] Create `backend/domain/knowledge_retriever.py`:
  ```python
  class KnowledgeRetriever:
      def get_core(self) -> str                                          # all core entries, always loaded
      def retrieve(self, query: str, scope: str | None, limit=5) -> str # semantic search over domain tier
      def retrieve_full_scope(self, scope: str) -> str                  # all entries in a scope
  ```
- [ ] `get_core()` loads all `tier='core'` entries, joins as markdown
- [ ] `retrieve()` embeds query → pgvector similarity search → format results
- [ ] Handle `{{SUBSCRIPTION_SERVICE_URL}}` replacement after retrieval

**Files**: `backend/domain/knowledge_retriever.py` (new)

### 2.4 Seed knowledge from `.md` files

- [ ] Create `backend/domain/seed_knowledge.py` — one-time migration script
- [ ] Chunking:
  - `base.md` → **tier=core**, scope `identity`, 1 entry
  - `tech-support.md` → split by FAQ sections. First section (general instructions) → **tier=core**, scope `tech_support`. Rest → tier=domain, scope `tech_support`
  - `email-inbox.md` → tier=core, scope `email_inbox`, 1 entry
  - `support-triage.md` → tier=domain, scope `support_triage`, 1 entry
  - `payment-data-validation.md` → tier=domain, scope `contractor`, split by contractor type
  - `claude-code-context.md` → tier=domain, scope `code`, 1 entry
- [ ] Generate embeddings for each chunk via `EmbeddingGateway`
- [ ] Insert with `source='seed'`
- [ ] Keep `.md` files in repo as historical record
- [ ] Run seed script and verify entries

**Files**: `backend/domain/seed_knowledge.py` (new)

### 2.5 Tests

- [ ] Create `tests/test_knowledge_retriever.py` — mock DB and embeddings, test retrieval logic
- [ ] Run tests

---

## Phase 3: Prompt Composition Evolution

### 3.1 Update compose_request.py

- [ ] Add module-level lazy `_retriever = None` with getter function
- [ ] Update `support_email()`:
  - Before: `load_knowledge("base.md", "email-inbox.md", "tech-support.md")`
  - After: `_retriever.get_core()` + `_retriever.retrieve(email_text, "tech_support", 5)`
- [ ] Update `tech_support_question()`:
  - Before: `load_knowledge("base.md", "tech-support.md")`
  - After: `_retriever.get_core()` + `_retriever.retrieve(question, "tech_support", 5)`
- [ ] Update `support_triage()`:
  - Before: `load_knowledge("support-triage.md")`
  - After: `_retriever.retrieve_full_scope("support_triage")`
- [ ] Update `contractor_parse()`:
  - Before: `load_knowledge("base.md", "payment-data-validation.md")`
  - After: `_retriever.get_core()` + `_retriever.retrieve_full_scope("contractor")`
- [ ] Leave `load_knowledge()` in `prompt_loader.py` untouched — backward compat
- [ ] Leave classification-only functions unchanged: `inbox_classify`, `editorial_assess`, `translate_name`, `classify_command`, `tech_search_terms`

**Files**: `backend/domain/compose_request.py`

### 3.2 Add conversation_reply function

- [ ] Add `conversation_reply(message, conversation_history, knowledge_context) -> tuple[str, str, list[str]]` to compose_request.py
- [ ] Add model entry: `"conversation_reply": "gemini-2.5-flash"`

**Files**: `backend/domain/compose_request.py`

### 3.3 New template: `templates/conversation.md`

- [ ] Create template:
  ```markdown
  Ты — напарник Луки, издатель Republic. Ведёшь диалог в Telegram.
  Используй контекст. Отвечай по-русски, кратко и по делу.
  Если не знаешь ответа — скажи.
  {{VERBOSE}}

  ## Контекст
  {{KNOWLEDGE}}

  ## История разговора
  {{CONVERSATION}}

  ## Сообщение
  {{MESSAGE}}

  Верни JSON: {"reply": "<ответ>"}
  ```

**Files**: `templates/conversation.md` (new)

### 3.4 Tests

- [ ] Test `support_email()` with mocked retriever returns same structure
- [ ] Test `tech_support_question()` with mocked retriever
- [ ] Compare prompt quality before/after with real examples
- [ ] Run full test suite

---

## Phase 4: Conversation Persistence

### 4.1 New table: `conversations`

- [ ] Add to `_SCHEMA_SQL` in `db_gateway.py`:
  ```sql
  CREATE TABLE IF NOT EXISTS conversations (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      chat_id BIGINT NOT NULL,
      user_id BIGINT NOT NULL,
      role TEXT NOT NULL,              -- 'user' | 'assistant'
      content TEXT NOT NULL,
      reply_to_id UUID REFERENCES conversations(id),
      message_id BIGINT,              -- Telegram message_id for linking
      metadata JSONB DEFAULT '{}',    -- {command: "support", channel: "dm"|"group"}
      created_at TIMESTAMP DEFAULT NOW()
  );
  CREATE INDEX IF NOT EXISTS idx_conv_chat ON conversations(chat_id, created_at);
  CREATE INDEX IF NOT EXISTS idx_conv_msg ON conversations(chat_id, message_id);
  CREATE INDEX IF NOT EXISTS idx_conv_reply ON conversations(reply_to_id);
  ```

### 4.2 DbGateway methods

- [ ] `save_conversation(chat_id, user_id, role, content, reply_to_id=None, message_id=None, metadata=None) -> str` — returns UUID
- [ ] `get_conversation_by_message_id(chat_id, message_id) -> dict | None`
- [ ] `get_reply_chain(conversation_id, depth=10) -> list[dict]` — walk reply_to_id chain upward, return chronological order

**Files**: `backend/infrastructure/gateways/db_gateway.py`

### 4.3 Save conversations at key points

- [ ] Update `_send_html` to return `types.Message` (already done — verify)
- [ ] In `cmd_support`: after sending answer, save both user question + bot answer to `conversations` table
- [ ] In `cmd_nl` (not classified path): after sending reply, save user text + bot reply
- [ ] In `cmd_code`: after sending answer, save user text + bot answer
- [ ] In `handle_group_message` (NL path): after sending reply, save user text + bot reply

**Files**: `telegram_bot/flow_callbacks.py`

### 4.4 Tests

- [ ] Test `save_conversation` + `get_conversation_by_message_id` + `get_reply_chain`
- [ ] Run tests

---

## Phase 5: Conversation NL Reply (Reply-to-Bot)

### 5.1 Reply routing chain in `handle_admin_reply`

- [ ] Modify `handle_admin_reply` to be a routing chain:
  ```
  1. Check _admin_reply_map → Legium forwarding (existing)
  2. Check _support_draft_map → Email draft feedback (Phase 6)
  3. Default → _handle_nl_reply (NL conversation)
  ```
- [ ] Guard: skip NL if FSM state is active (`await state.get_state() is not None`)
- [ ] Guard: only trigger for replies to BOT messages (`reply.from_user.is_bot`)

**Files**: `telegram_bot/flow_callbacks.py`

### 5.2 Implement `_handle_nl_reply`

- [ ] Query `conversations` table for reply chain context
- [ ] If no DB record, bootstrap from `reply.reply_to_message.text`
- [ ] Retrieve relevant knowledge via `KnowledgeRetriever.retrieve(question)`
- [ ] Format conversation history for prompt
- [ ] Call LLM via `compose_request.conversation_reply()`
- [ ] Reply to user's message with `reply_to_message_id=message.message_id` (maintains visual chain)
- [ ] Save both turns to `conversations` table with `reply_to_id` linking
- [ ] Truncate answer to 4000 chars if needed

**Files**: `telegram_bot/flow_callbacks.py`

### 5.3 Group chat integration

- [ ] In `handle_group_message`, when `not result.classified` and `is_reply_to_bot`: call `_handle_nl_reply` instead of showing generic classifier reply
- [ ] If `_handle_nl_reply` returns False (guards failed), fall back to existing behavior

**Files**: `telegram_bot/flow_callbacks.py`

### 5.4 Tests

- [ ] Test `_handle_nl_reply` with mocked DB and LLM
- [ ] Test reply chain context building
- [ ] Test that legium forwarding still works (priority 1)
- [ ] Test that FSM states are respected
- [ ] Run full test suite

---

## Phase 6: Learning from Admin Feedback

### 6.1 Track draft messages

- [ ] Add `_support_draft_map: dict[tuple[int, int], str]` mapping `(chat_id, message_id) → uid`
- [ ] In `_send_support_draft`: after `bot.send_message`, register in `_support_draft_map`

**Files**: `telegram_bot/flow_callbacks.py`

### 6.2 Handle admin replies to drafts

- [ ] In `handle_admin_reply` routing chain (Phase 5.1), check `_support_draft_map` before NL fallback
- [ ] Classify admin reply:
  - If starts with greeting (Здравствуйте, Добрый день, Hello, Dear) → replacement draft: send this text instead
  - Otherwise → teaching feedback: store as knowledge + skip original
- [ ] For replacement: call `_inbox.update_and_approve_support(uid, new_reply_text)` or equivalent
- [ ] For teaching: store via `KnowledgeRetriever.store_feedback(text, scope="tech_support")`
- [ ] In both cases, remove from `_support_draft_map`

**Files**: `telegram_bot/flow_callbacks.py`, `backend/domain/inbox_service.py` (minor)

### 6.3 Store feedback as knowledge

- [ ] Add `store_feedback(text, scope, metadata=None)` to `KnowledgeRetriever`:
  - Generate embedding
  - Save as `knowledge_entries` with `tier='domain'`, `source='admin_feedback'`

**Files**: `backend/domain/knowledge_retriever.py`

### 6.4 Tests

- [ ] Test replacement draft path
- [ ] Test teaching feedback path → verify knowledge_entries created
- [ ] Test that Send/Skip buttons still work alongside reply path
- [ ] Run tests

---

## Phase 7: Admin Teaching

### 7.1 `/teach` command

- [ ] Add `cmd_teach(message, state)` in `flow_callbacks.py`:
  - Parse text after `/teach`
  - Generate embedding
  - Store as `knowledge_entries` with `tier='domain'`, `source='admin_teach'`
  - Reply "Запомнил."
- [ ] Register in `flows.py` as admin command

**Files**: `telegram_bot/flow_callbacks.py`, `telegram_bot/flows.py`

### 7.2 Teaching through NL conversation

- [ ] In `_handle_nl_reply`, detect teaching patterns: "запомни", "учти", "имей в виду", "remember"
- [ ] When detected: store as knowledge entry AND reply conversationally (confirming storage)
- [ ] Simple keyword detection, no LLM classification needed

**Files**: `telegram_bot/flow_callbacks.py`

### 7.3 Knowledge management commands

- [ ] Add `cmd_knowledge(message, state)`:
  - `/knowledge` — list all active entries (id, tier, scope, title, source, created_at)
  - `/knowledge <scope>` — filter by scope
- [ ] Add `cmd_forget(message, state)`:
  - `/forget <id>` — soft-delete a knowledge entry
- [ ] Add `cmd_knowledge_edit(message, state)`:
  - `/kedit <id>` — show current content, wait for new content via reply
  - Or: `/kedit <id> <new content>` — inline update
- [ ] Register all in `flows.py`

**Files**: `telegram_bot/flow_callbacks.py`, `telegram_bot/flows.py`

### 7.4 Tests

- [ ] Test `/teach` stores entry with correct tier/scope/source
- [ ] Test NL teaching detection
- [ ] Test `/knowledge` listing
- [ ] Test `/forget` soft-deletes
- [ ] Run full test suite

---

## Implementation Order

```
Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → Phase 6 → Phase 7
  │          │          │          │          │          │          │
  │          │          │          │          │          │          └─ /teach, NL teaching, /knowledge, /forget
  │          │          │          │          │          └─ Reply to drafts → learn or send corrected
  │          │          │          │          └─ Reply-to-bot → NL conversation with DB context
  │          │          │          └─ conversations table, save at key points
  │          │          └─ compose_request uses retriever, conversation.md template
  │          └─ knowledge_entries table, retriever, seed migration
  └─ pgvector extension, embedding gateway
```

Each phase is independently deployable. No phase breaks existing behavior.

## Files Summary

**New files (6):**
| File | Phase |
|---|---|
| `backend/infrastructure/gateways/embedding_gateway.py` | 1 |
| `backend/domain/knowledge_retriever.py` | 2 |
| `backend/domain/seed_knowledge.py` | 2 |
| `templates/conversation.md` | 3 |
| `tests/test_embedding_gateway.py` | 1 |
| `tests/test_knowledge_retriever.py` | 2 |

**Modified files (5):**
| File | Phases |
|---|---|
| `backend/infrastructure/gateways/db_gateway.py` | 1, 2, 4 |
| `backend/domain/compose_request.py` | 3 |
| `telegram_bot/flow_callbacks.py` | 4, 5, 6, 7 |
| `telegram_bot/flows.py` | 7 |
| `telegram_bot/bot_helpers.py` | 4 (minor) |

**No new dependencies.** Uses existing `google-genai`, `psycopg2-binary`, pgvector Docker image.
