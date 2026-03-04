# Phase 5: Environments + Prompt Pipeline

> Foundation for WHERE-awareness. The brain learns which context it's operating in
> and tailors knowledge retrieval + prompt assembly accordingly.
>
> Polar: (a) environments are DB-persisted — editable via bot commands, no code deploys.
> (b) adding a new environment = one INSERT, zero code changes.

## 5.0 Pre-flight

- [x] 5.0.1 Read current schema in `backend/infrastructure/repositories/postgres/base.py` (lines 9-120)
- [x] 5.0.2 Read `knowledge_repo.py` methods: `search_knowledge` (line 33), `get_domain_context` (line 83)
- [x] 5.0.3 Read `conversation_service.py`: `generate_nl_reply` (line 41), `build_conversation_context` (line 20)
- [x] 5.0.4 Read `compose_request.py`: `conversation_reply` (line 129)
- [x] 5.0.5 Read `templates/conversation.md` (14 lines)
- [x] 5.0.6 Run `pytest` — all tests pass (baseline)

---

## 5.1 Schema: environments + bindings tables

> Two new tables. An environment is WHERE the brain operates.
> A binding maps a concrete chat_id to an environment.

- [x] 5.1.1 Add to `_SCHEMA_SQL` in `base.py` (after conversations block, ~line 119):
  ```sql
  CREATE TABLE IF NOT EXISTS environments (
      name         TEXT PRIMARY KEY,
      description  TEXT NOT NULL DEFAULT '',
      system_context TEXT NOT NULL DEFAULT '',
      allowed_domains TEXT[],
      created_at   TIMESTAMPTZ DEFAULT NOW(),
      updated_at   TIMESTAMPTZ DEFAULT NOW()
  );

  CREATE TABLE IF NOT EXISTS environment_bindings (
      chat_id      BIGINT PRIMARY KEY,
      environment  TEXT NOT NULL REFERENCES environments(name),
      created_at   TIMESTAMPTZ DEFAULT NOW()
  );
  ```
- [x] 5.1.2 Add seed data migration (after CREATE TABLE, still in `_SCHEMA_SQL`):
  ```sql
  INSERT INTO environments (name, description, system_context, allowed_domains) VALUES
    ('admin_dm', 'Приватный чат с администратором Republic',
     'Это приватный чат с администратором. Полный доступ ко всем функциям. Можно обсуждать внутренние вопросы, контрагентов, бюджет. Давай развёрнутые ответы.',
     NULL),
    ('editorial_group', 'Групповой чат редакции Republic',
     'Это групповой чат редакции. Видят все сотрудники. Отвечай кратко и по делу. Не раскрывай персональные данные контрагентов.',
     ARRAY['tech_support', 'editorial', 'identity']),
    ('contractor_dm', 'Личный чат с контрагентом Republic',
     'Это личный чат с контрагентом Republic. Будь вежлив и формален. Помогай с документами, оплатой, регистрацией.',
     ARRAY['contractor', 'payments']),
    ('email', 'Обработка входящей почты',
     'Ты составляешь ответ на email. Пиши формально и грамотно.',
     ARRAY['tech_support'])
  ON CONFLICT (name) DO NOTHING;
  ```
- [x] 5.1.3 Run `pytest` — all tests pass (schema change is additive, no breakage)

---

## 5.2 Repository: EnvironmentRepo

> New repo file for environment CRUD. Follows existing repo pattern (extends BasePostgresRepo).

- [x] 5.2.1 Create `backend/infrastructure/repositories/postgres/environment_repo.py`:
  ```python
  class EnvironmentRepo(BasePostgresRepo):
      def get_environment(self, name: str) -> dict | None
      def get_environment_by_chat_id(self, chat_id: int) -> dict | None
      def list_environments(self) -> list[dict]
      def save_environment(self, name: str, description: str, system_context: str,
                           allowed_domains: list[str] | None = None) -> str
      def update_environment(self, name: str, **fields) -> bool
      def bind_chat(self, chat_id: int, environment: str) -> None
      def unbind_chat(self, chat_id: int) -> None
  ```
  - `get_environment_by_chat_id`: JOIN environment_bindings → environments. Returns full environment dict or None.
  - `save_environment`: INSERT or UPDATE on conflict.
  - `update_environment`: accepts keyword args for any updatable column (description, system_context, allowed_domains). Only updates provided fields.
- [x] 5.2.2 Add `EnvironmentRepo` to `DbGateway` in `postgres/__init__.py` (multiple inheritance, same pattern as others)
- [x] 5.2.3 Write tests in `tests/infrastructure/repositories/postgres/test_environment_repo.py`:
  - `test_save_and_get_environment`
  - `test_get_environment_by_chat_id`
  - `test_get_environment_by_chat_id_unbound_returns_none`
  - `test_bind_chat_and_rebind`
  - `test_list_environments`
  - `test_update_environment_partial_fields`
- [x] 5.2.4 Run `pytest` — all tests pass

---

## 5.3 Seed binding for editorial chat

> Wire the existing `EDITORIAL_CHAT_ID` config to the `editorial_group` environment.

- [x] 5.3.1 Add migration in `_SCHEMA_SQL` (after environment seeds):
  ```sql
  -- Bind editorial chat if EDITORIAL_CHAT_ID is set (handled in Python init)
  ```
  Actually: do this in Python. In `base.py:init_schema()` or a new `seed_bindings()` method:
  ```python
  def _seed_editorial_binding(self):
      from common.config import EDITORIAL_CHAT_ID
      if EDITORIAL_CHAT_ID:
          self._get_conn().cursor().execute(
              "INSERT INTO environment_bindings (chat_id, environment) VALUES (%s, %s) ON CONFLICT DO NOTHING",
              (EDITORIAL_CHAT_ID, "editorial_group"),
          )
  ```
  Call from `init_schema()` after `_SCHEMA_SQL` execution.
- [x] 5.3.2 Add migration for admin DM: bind admin chat_ids from `ADMIN_TELEGRAM_IDS` config to `admin_dm`.
  Same pattern: iterate ADMIN_TELEGRAM_IDS, bind each to `admin_dm`. (Note: these are user IDs, not chat IDs. In DMs, chat_id == user_id.)
- [x] 5.3.3 Run `pytest` — all tests pass

---

## 5.4 Domain-filtered RAG retrieval

> `search_knowledge` already accepts `domain` param. Now add multi-domain filtering
> so environments with `allowed_domains = ['tech_support', 'editorial']` scope RAG correctly.

- [x] 5.4.1 Add method to `KnowledgeRepo` (knowledge_repo.py):
  ```python
  def search_knowledge_multi_domain(
      self, query_embedding: list[float],
      domains: list[str] | None = None,
      limit: int = 5,
  ) -> list[dict]:
  ```
  - If `domains` is None → no domain filter (same as current `search_knowledge` with domain=None)
  - If `domains` is a list → `WHERE domain = ANY(%s)` filter
  - Same return shape as `search_knowledge`
- [x] 5.4.2 Add `retrieve` overload to `KnowledgeRetriever` (knowledge_retriever.py):
  - Change signature: `retrieve(self, query: str, domain: str | None = None, domains: list[str] | None = None, limit: int = 5) -> str`
  - If `domains` provided, use `search_knowledge_multi_domain`
  - If `domain` (singular) provided, use existing `search_knowledge`
  - If neither, search all
- [x] 5.4.3 Similarly update `get_domain_context` to accept `domains: list[str]` variant:
  - When given a list, return core + meta entries for ALL listed domains
  - Add `get_multi_domain_context(self, domains: list[str]) -> str` to keep methods clean
- [x] 5.4.4 Write tests:
  - `test_search_knowledge_multi_domain_filters_correctly`
  - `test_search_knowledge_multi_domain_none_returns_all`
  - `test_retrieve_with_domains_list`
  - `test_get_multi_domain_context`
- [x] 5.4.5 Run `pytest` — all tests pass

---

## 5.5 Thread environment through prompt assembly

> The core change: `generate_nl_reply` accepts environment context and passes it to the template.

- [ ] 5.5.1 Update `templates/conversation.md`:
  ```markdown
  Отвечай по-русски.
  Если не знаешь ответа — скажи.
  {{VERBOSE}}

  ## Окружение
  {{ENVIRONMENT}}

  ## Контекст
  {{KNOWLEDGE}}

  ## История разговора
  {{CONVERSATION}}

  ## Сообщение
  {{MESSAGE}}

  Верни JSON: {"reply": "<ответ>"}
  ```
- [ ] 5.5.2 Update `compose_request.conversation_reply()` (line 129):
  - Add parameters: `environment_context: str = ""`, `user_context: str = ""`
  - Pass `ENVIRONMENT` to template: `environment_context or "(контекст не указан)"`
  - If `user_context` is non-empty, append it under `## О собеседнике` section (or add another template placeholder — keep it simple, just concat into ENVIRONMENT for now)
- [ ] 5.5.3 Update `conversation_service.generate_nl_reply()` (line 41):
  - Add parameters: `environment: str = ""`, `allowed_domains: list[str] | None = None`
  - When `allowed_domains` is given, use `retriever.retrieve(query, domains=allowed_domains)` and `retriever.get_multi_domain_context(allowed_domains)`
  - When `allowed_domains` is None, use current behavior (get_core + retrieve all)
  - Pass `environment` to `compose_request.conversation_reply(..., environment_context=environment)`
- [ ] 5.5.4 Update all 3 call sites of `generate_nl_reply`:
  1. `conversation_handlers.py:_handle_nl_reply` (line 92) — look up environment by `message.chat.id`, pass `environment=env.system_context`, `allowed_domains=env.allowed_domains`
  2. `conversation_handlers.py:cmd_nl` (line 131) — same lookup
  3. `router.py:handle_group_message` (line 261) — same lookup
  - Create a shared helper: `_resolve_environment(chat_id: int) -> tuple[str, list[str] | None]` that returns `(system_context, allowed_domains)`. Place it in `handler_utils.py` since all 3 call sites already import from there.
  - The helper calls `_db.get_environment_by_chat_id(chat_id)`. If no binding found, returns `("", None)` — no environment context, no domain filter (backward-compatible).
- [ ] 5.5.5 Update tests:
  - `test_compose_request.py`: update `conversation_reply` tests for new params (backward-compat: old calls without params still work)
  - `test_conversation_service.py`: test `generate_nl_reply` with environment + allowed_domains
  - `test_conversation_handlers.py`: update patches, test that environment is resolved and passed through
  - `test_plan2_handlers.py`: update group handler test patches if needed
- [ ] 5.5.6 Run `pytest` — all tests pass

---

## 5.6 Fix teaching security gap

> Teaching via `_TEACHING_KEYWORDS` should only work for admins.

- [ ] 5.6.1 In `conversation_handlers.py:_handle_nl_reply` (line 76), wrap teaching block:
  ```python
  if any(kw in user_text_lower for kw in _TEACHING_KEYWORDS):
      if is_admin(message.from_user.id):  # ← add this check
          try:
              ...
  ```
  Add `from telegram_bot.bot_helpers import is_admin` to imports.
- [ ] 5.6.2 Write test: `test_teaching_keywords_ignored_for_non_admin`
- [ ] 5.6.3 Run `pytest` — all tests pass

---

## 5.7 Teaching deduplication

> Before storing a new teaching, check embedding similarity against existing entries.
> If match > 0.90, update existing entry instead of creating duplicate.

- [ ] 5.7.1 Modify `KnowledgeRetriever.store_teaching()` (knowledge_retriever.py, line 55):
  ```python
  def store_teaching(self, text: str, domain: str = "general", tier: str = "specific") -> str:
      embedding = self._embed.embed_one(text)
      existing = self._db.search_knowledge(embedding, domain=domain, limit=1)
      if existing and existing[0].get("similarity", 0) > 0.90:
          entry_id = existing[0]["id"]
          self._db.update_knowledge_entry(entry_id, text, embedding)
          return entry_id
      title = text[:60].strip()
      return self._db.save_knowledge_entry(
          tier=tier, domain=domain, title=title,
          content=text, source="admin_teach", embedding=embedding,
      )
  ```
- [ ] 5.7.2 Same for `store_feedback()` (line 43) — apply identical dedup logic.
- [ ] 5.7.3 Write tests:
  - `test_store_teaching_deduplicates_similar`
  - `test_store_teaching_creates_new_when_different`
- [ ] 5.7.4 Run `pytest` — all tests pass

---

## 5.8 Bot commands for environment management

> Admin should be able to manage environments via Telegram, not just SQL.

- [ ] 5.8.1 Add commands to `conversation_handlers.py`:
  ```python
  async def cmd_env(message: types.Message, state: FSMContext) -> None:
      """List environments or show details: /env [name]"""

  async def cmd_env_edit(message: types.Message, state: FSMContext) -> None:
      """Edit environment field: /env_edit <name> <field> <value>
      Fields: description, system_context, allowed_domains"""

  async def cmd_env_bind(message: types.Message, state: FSMContext) -> None:
      """Bind current chat to environment: /env_bind <name>"""
  ```
- [ ] 5.8.2 Register in `router.py:_ADMIN_COMMANDS` dict
- [ ] 5.8.3 Write tests for each command:
  - `test_cmd_env_lists_all`
  - `test_cmd_env_shows_details`
  - `test_cmd_env_edit_updates_system_context`
  - `test_cmd_env_bind_binds_current_chat`
- [ ] 5.8.4 Run `pytest` — all tests pass

---

## 5.9 Verification

- [ ] 5.9.1 Run full `pytest` suite — all tests pass
- [ ] 5.9.2 Manual: send @mention in editorial group → bot reply should include editorial_group system_context in its prompt (verify via logs or response tone)
- [ ] 5.9.3 Manual: `/env` in admin DM → shows all environments with bindings
- [ ] 5.9.4 Manual: `/env_bind editorial_group` in a new group chat → binds it
- [ ] 5.9.5 Commit: `feat: add environment-aware prompt assembly (WHERE layer)`

---

## Design Notes

**Adding a new environment (zero code changes):**
1. `/env_edit new_channel description "Канал для SMM"` → creates environment
2. `/env_edit new_channel system_context "Ты помогаешь с SMM-контентом..."` → sets behavior
3. `/env_edit new_channel allowed_domains smm,editorial` → scopes RAG
4. `/env_bind new_channel` (from the target chat) → binds chat_id

**Modifying existing environment:**
1. `/env_edit editorial_group system_context "Updated instructions..."` → immediate effect, no restart

**Fallback behavior:**
- Unbound chat_id → no environment context, no domain filter, same as current behavior
- Environment with `allowed_domains = NULL` → no domain filter (admin_dm can access everything)
