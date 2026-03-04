# Phase 6: Entities + Knowledge Extensions

> Foundation for WHO-awareness. The brain learns about people, organizations,
> and other entities it interacts with or discusses.
>
> Polar: (a) adding a new entity = one INSERT + optional knowledge links, zero code changes.
> (b) entity knowledge is just regular knowledge_entries with an entity_id FK —
> no parallel storage, no special retrieval paths, same RAG pipeline.

## 6.0 Pre-flight

- [x] 6.0.1 Confirm Phase 5 is complete (environments working, tests passing)
- [x] 6.0.2 Read current `knowledge_repo.py` — understand `search_knowledge` return shape
- [x] 6.0.3 Read `knowledge_retriever.py` — understand `retrieve()` and `get_domain_context()`
- [x] 6.0.4 Read `compose_request.py:conversation_reply()` — confirm `environment_context` param exists (Phase 5)
- [x] 6.0.5 Run `pytest` — all tests pass (baseline)

---

## 6.1 Schema: entities table

> An entity is anyone or anything the brain has knowledge about.

- [x] 6.1.1 Add to `_SCHEMA_SQL` in `base.py`:
  ```sql
  CREATE TABLE IF NOT EXISTS entities (
      id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      kind          TEXT NOT NULL,
      name          TEXT NOT NULL,
      external_ids  JSONB DEFAULT '{}',
      summary       TEXT NOT NULL DEFAULT '',
      embedding     vector(256),
      created_at    TIMESTAMPTZ DEFAULT NOW(),
      updated_at    TIMESTAMPTZ DEFAULT NOW()
  );

  CREATE INDEX IF NOT EXISTS idx_entity_kind ON entities(kind);
  CREATE INDEX IF NOT EXISTS idx_entity_external_ids ON entities USING GIN(external_ids);
  CREATE INDEX IF NOT EXISTS idx_entity_name ON entities(name);
  ```
  - `kind`: 'person', 'organization', 'publication', 'product', 'competitor'
  - `external_ids`: `{"telegram_user_id": 123, "email": "x@y.com", "airtable_id": "rec..."}`
  - `summary`: human-readable summary, updated as knowledge grows
  - `embedding`: for entity similarity search / clustering (embed the name+summary)
- [x] 6.1.2 Run `pytest` — all tests pass (additive schema change)

---

## 6.2 Schema: link knowledge_entries to entities

> Entity-specific knowledge is regular knowledge_entries with an entity_id FK.
> "Иванов предпочитает оплату на карту" → knowledge entry with entity_id = Иванов's UUID.

- [x] 6.2.1 Add to `_SCHEMA_SQL` in `base.py`:
  ```sql
  -- Entity FK on knowledge_entries
  DO $$ BEGIN
      ALTER TABLE knowledge_entries ADD COLUMN entity_id UUID REFERENCES entities(id);
  EXCEPTION WHEN duplicate_column THEN NULL;
  END $$;

  CREATE INDEX IF NOT EXISTS idx_knowledge_entity
      ON knowledge_entries(entity_id) WHERE entity_id IS NOT NULL;
  ```
- [x] 6.2.2 Run `pytest` — all tests pass (nullable column, no breakage)

---

## 6.3 Schema: knowledge_entries provenance columns

> Source tracking for future crawlers and knowledge pipelines.

- [x] 6.3.1 Add to `_SCHEMA_SQL` in `base.py`:
  ```sql
  DO $$ BEGIN
      ALTER TABLE knowledge_entries ADD COLUMN source_url TEXT;
  EXCEPTION WHEN duplicate_column THEN NULL;
  END $$;

  DO $$ BEGIN
      ALTER TABLE knowledge_entries ADD COLUMN expires_at TIMESTAMPTZ;
  EXCEPTION WHEN duplicate_column THEN NULL;
  END $$;

  DO $$ BEGIN
      ALTER TABLE knowledge_entries ADD COLUMN parent_id UUID REFERENCES knowledge_entries(id);
  EXCEPTION WHEN duplicate_column THEN NULL;
  END $$;
  ```
  - `source_url`: URL of crawled page, article, etc. For provenance and dedup.
  - `expires_at`: NULL = eternal. Non-null = temporal knowledge (competitor pricing, event dates).
  - `parent_id`: self-FK. Summaries/derivatives link to their source entry.
- [x] 6.3.2 Update `search_knowledge` and `search_knowledge_multi_domain` in `knowledge_repo.py`:
  - Add `WHERE (expires_at IS NULL OR expires_at > NOW())` to filter expired entries
- [x] 6.3.3 Update `save_knowledge_entry` signature to accept optional `entity_id`, `source_url`, `expires_at`, `parent_id`
- [x] 6.3.4 Write tests:
  - `test_expired_entries_excluded_from_search`
  - `test_non_expired_entries_included`
  - `test_null_expires_always_included`
  - `test_save_entry_with_source_url`
  - `test_save_entry_with_entity_id`
- [x] 6.3.5 Run `pytest` — all tests pass

---

## 6.4 Repository: EntityRepo

> CRUD for entities. Follows existing repo pattern.

- [x] 6.4.1 Create `backend/infrastructure/repositories/postgres/entity_repo.py`:
  ```python
  class EntityRepo(BasePostgresRepo):

      def save_entity(self, kind: str, name: str,
                      external_ids: dict | None = None,
                      summary: str = "",
                      embedding: list[float] | None = None) -> str:
          """Insert entity, return UUID."""

      def get_entity(self, entity_id: str) -> dict | None:
          """Fetch by ID."""

      def find_entity_by_external_id(self, key: str, value) -> dict | None:
          """Find by external_ids->>key = value. E.g. find_entity_by_external_id('telegram_user_id', 123)."""

      def find_entities_by_name(self, name_query: str, limit: int = 5) -> list[dict]:
          """Case-insensitive LIKE search on name."""

      def update_entity(self, entity_id: str, **fields) -> bool:
          """Partial update. Accepts: name, summary, external_ids, embedding."""

      def search_entities(self, query_embedding: list[float], limit: int = 5) -> list[dict]:
          """Vector similarity search over entity embeddings."""

      def get_entity_knowledge(self, entity_id: str, limit: int = 10) -> list[dict]:
          """Fetch knowledge_entries WHERE entity_id = ?. Ordered by created_at DESC."""

      def list_entities(self, kind: str | None = None) -> list[dict]:
          """List all entities, optionally filtered by kind."""
  ```
- [x] 6.4.2 Add `EntityRepo` to `DbGateway` in `postgres/__init__.py`
- [x] 6.4.3 Write tests in `tests/infrastructure/repositories/postgres/test_entity_repo.py`:
  - `test_save_and_get_entity`
  - `test_find_entity_by_external_id`
  - `test_find_entity_by_external_id_not_found`
  - `test_find_entities_by_name`
  - `test_update_entity_partial`
  - `test_get_entity_knowledge`
  - `test_list_entities_by_kind`
- [x] 6.4.4 Run `pytest` — all tests pass

---

## 6.5 KnowledgeRetriever: entity-aware retrieval

> When the brain knows WHO it's talking to, entity-linked knowledge gets loaded.

- [ ] 6.5.1 Add method to `KnowledgeRetriever`:
  ```python
  def get_entity_context(self, entity_id: str) -> str:
      """Fetch entity summary + entity-linked knowledge entries. Format as markdown."""
      entity = self._db.get_entity(entity_id)
      if not entity:
          return ""
      parts = []
      if entity.get("summary"):
          parts.append(f"## {entity['name']}\n{entity['summary']}")
      entries = self._db.get_entity_knowledge(entity_id, limit=5)
      if entries:
          parts.append(_format_entries(entries))
      return "\n\n".join(parts)
  ```
- [ ] 6.5.2 Add method to `KnowledgeRetriever`:
  ```python
  def store_entity_knowledge(self, entity_id: str, text: str,
                              domain: str = "general") -> str:
      """Store a knowledge entry linked to an entity. Dedup-aware."""
      embedding = self._embed.embed_one(text)
      # Check for near-duplicates scoped to this entity
      existing = self._db.get_entity_knowledge(entity_id, limit=10)
      for entry in existing:
          if entry.get("embedding"):
              # Compare similarity (would need a helper or DB call)
              pass
      # Simplified: just store with entity_id
      title = text[:60].strip()
      return self._db.save_knowledge_entry(
          tier="specific", domain=domain, title=title,
          content=text, source="admin_teach",
          embedding=embedding, entity_id=entity_id,
      )
  ```
- [ ] 6.5.3 Write tests:
  - `test_get_entity_context_formats_correctly`
  - `test_get_entity_context_missing_entity`
  - `test_store_entity_knowledge`
- [ ] 6.5.4 Run `pytest` — all tests pass

---

## 6.6 Thread entity context into prompt assembly

> Layer 4 of the prompt stack: WHO am I talking to?

- [ ] 6.6.1 Update `compose_request.conversation_reply()`:
  - Confirm `user_context` param exists from Phase 5 (it was added as param but may concatenate into ENVIRONMENT)
  - If not yet a separate template slot, add `{{USER_CONTEXT}}` to `conversation.md`:
    ```markdown
    ## О собеседнике
    {{USER_CONTEXT}}
    ```
  - Pass through in `conversation_reply`: `"USER_CONTEXT": user_context or ""`
- [ ] 6.6.2 Update `generate_nl_reply()`:
  - Add parameter: `user_context: str = ""`
  - Pass to `compose_request.conversation_reply(..., user_context=user_context)`
- [ ] 6.6.3 Create helper in `handler_utils.py`:
  ```python
  def _resolve_entity_context(user_id: int) -> str:
      """Look up entity by telegram_user_id, return formatted context or empty string."""
      entity = _db.find_entity_by_external_id("telegram_user_id", user_id)
      if not entity:
          return ""
      retriever = _get_retriever()
      return retriever.get_entity_context(entity["id"])
  ```
- [ ] 6.6.4 Update all 3 call sites of `generate_nl_reply` to resolve and pass entity context:
  1. `conversation_handlers.py:_handle_nl_reply` — `user_context=_resolve_entity_context(message.from_user.id)`
  2. `conversation_handlers.py:cmd_nl` — same
  3. `router.py:handle_group_message` — same
- [ ] 6.6.5 Update tests for new parameter threading
- [ ] 6.6.6 Run `pytest` — all tests pass

---

## 6.7 Bot commands for entity management

> Admin manages entities via Telegram.

- [ ] 6.7.1 Add commands to `conversation_handlers.py`:
  ```python
  async def cmd_entity(message: types.Message, state: FSMContext) -> None:
      """List or search entities: /entity [query]"""
      # No args → list all entities (grouped by kind)
      # With args → fuzzy name search

  async def cmd_entity_add(message: types.Message, state: FSMContext) -> None:
      """Add entity: /entity_add <kind> <name>
      kinds: person, organization, publication, product, competitor"""

  async def cmd_entity_link(message: types.Message, state: FSMContext) -> None:
      """Link external ID: /entity_link <entity_name> telegram_user_id=123"""
      # Parses key=value pairs, updates external_ids

  async def cmd_entity_note(message: types.Message, state: FSMContext) -> None:
      """Add knowledge about entity: /entity_note <entity_name> <text>
      Stores as knowledge_entry with entity_id FK."""
  ```
- [ ] 6.7.2 Register in `router.py:_ADMIN_COMMANDS`
- [ ] 6.7.3 Write tests for each command
- [ ] 6.7.4 Run `pytest` — all tests pass

---

## 6.8 Auto-link contractors as entities

> Existing contractor data from sheets can be linked as entities.
> This is a one-time migration + ongoing sync.

- [ ] 6.8.1 Create use case `backend/domain/use_cases/sync_contractor_entities.py`:
  ```python
  def execute(contractors: list[Contractor], db: DbGateway, embed: EmbeddingGateway):
      """For each contractor, create/update a matching entity."""
      for c in contractors:
          existing = db.find_entity_by_external_id("contractor_name", c.name)
          if existing:
              db.update_entity(existing["id"], summary=_build_summary(c))
          else:
              db.save_entity(
                  kind="person",
                  name=c.name,
                  external_ids={"contractor_name": c.name, "contractor_type": c.type},
                  summary=_build_summary(c),
                  embedding=embed.embed_one(f"{c.name} {c.type}"),
              )
  ```
- [ ] 6.8.2 Wire into admin command: `/sync_entities` — runs the sync
- [ ] 6.8.3 Write tests
- [ ] 6.8.4 Run `pytest` — all tests pass

---

## 6.9 Verification

- [ ] 6.9.1 Run full `pytest` suite — all tests pass
- [ ] 6.9.2 Manual: `/entity_add person "Иван Петров"` → creates entity
- [ ] 6.9.3 Manual: `/entity_link Иван Петров telegram_user_id=12345` → links
- [ ] 6.9.4 Manual: `/entity_note Иван Петров Предпочитает оплату на карту` → stores linked knowledge
- [ ] 6.9.5 Manual: send message as linked user → bot response should reflect entity context
- [ ] 6.9.6 Commit: `feat: add entity system (WHO layer) + knowledge provenance columns`

---

## Design Notes

**Adding a new entity (zero code changes):**
1. `/entity_add competitor "Медуза"` → creates entity with kind=competitor
2. `/entity_note Медуза Основной конкурент в сегменте политической журналистики` → stores knowledge
3. Any future RAG query mentioning Медуза will surface this entity-linked knowledge

**Adding a new entity kind:**
- Just use it: `/entity_add publication "Republic Magazine"`. The `kind` column is free-text.
- No enum, no migration, no code change.

**Entity knowledge retrieval flow:**
1. Message arrives from user with `telegram_user_id=123`
2. `find_entity_by_external_id("telegram_user_id", 123)` → entity dict
3. `get_entity_context(entity_id)` → entity summary + linked knowledge entries
4. Injected as `{{USER_CONTEXT}}` in prompt Layer 4
5. LLM sees: "## О собеседнике\nИван Петров\nПредпочитает оплату на карту\n..."

**Provenance tracking:**
- `source_url` on knowledge_entries → "where did we get this?"
- `parent_id` → "what is this derived from?" (e.g., article summary → links to full article entry)
- `expires_at` → temporal knowledge auto-filtered from RAG results
