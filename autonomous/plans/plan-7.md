# Phase 7: Memory API + MCP Interface

> The brain gets an API. Any agent — Claude via MCP, a crawler script, a Slack bot —
> can read and write to the same memory store through a clean, uniform interface.
>
> Polar: (a) connecting a new data source = implement one `remember()` call, zero schema changes.
> (b) the MCP server is a thin adapter over existing services — no new logic, just exposure.

## 7.0 Pre-flight

- [x] 7.0.1 Confirm Phase 5 (environments) and Phase 6 (entities) are complete
- [x] 7.0.2 Read MCP Python SDK docs — understand `@mcp.tool()` decorator, server setup
- [x] 7.0.3 Inventory all existing backend service methods that the MCP should expose
- [x] 7.0.4 Run `pytest` — all tests pass (baseline: 1323 tests)

---

## 7.1 Memory Service: unified API layer

> Before exposing via MCP, formalize the memory API as a backend service.
> This service is the single gateway to the brain — bot handlers, MCP server,
> and future clients all go through it.

- [x] 7.1.1 Create `backend/domain/services/memory_service.py`:
  ```python
  class MemoryService:
      def __init__(self, db: DbGateway | None = None,
                   embed: EmbeddingGateway | None = None,
                   retriever: KnowledgeRetriever | None = None):
          self._db = db or DbGateway()
          self._embed = embed or EmbeddingGateway()
          self._retriever = retriever or KnowledgeRetriever(self._db, self._embed)
  ```

  **Core operations:**

  ```python
  # ── REMEMBER ────────────────────────────────────────────────────
  def remember(self, text: str, domain: str, source: str = "api",
               tier: str = "specific", entity_id: str | None = None,
               source_url: str | None = None,
               expires_at: datetime | None = None) -> str:
      """Store a knowledge entry. Returns entry UUID.
      Deduplication: if embedding similarity > 0.90 in same domain, updates existing."""

  # ── RECALL ─────────────────────────────────────────────────────
  def recall(self, query: str, domain: str | None = None,
             domains: list[str] | None = None,
             entity_id: str | None = None,
             limit: int = 5) -> list[dict]:
      """Retrieve relevant knowledge. Returns list of {id, title, content, similarity, domain}."""

  # ── TEACH ──────────────────────────────────────────────────────
  def teach(self, text: str, domain: str | None = None,
            tier: str | None = None) -> str:
      """Classify + store teaching. Auto-detects domain/tier if not provided.
      Returns entry UUID."""

  # ── CONTEXT ────────────────────────────────────────────────────
  def get_context(self, environment: str | None = None,
                  chat_id: int | None = None,
                  user_id: int | None = None,
                  query: str = "") -> dict:
      """Assemble full prompt context for an environment + entity.
      Returns {environment: str, knowledge: str, user_context: str, domains: list}."""

  # ── ENTITY OPS ─────────────────────────────────────────────────
  def add_entity(self, kind: str, name: str,
                 external_ids: dict | None = None,
                 summary: str = "") -> str:
      """Create entity. Returns UUID."""

  def find_entity(self, query: str = "", external_key: str = "",
                  external_value: str = "") -> dict | None:
      """Find entity by name search or external_id lookup."""

  def update_entity_summary(self, entity_id: str, summary: str) -> bool:
      """Update entity summary + re-embed."""

  # ── ENVIRONMENT OPS ────────────────────────────────────────────
  def list_environments(self) -> list[dict]:
  def get_environment(self, name: str = "", chat_id: int = 0) -> dict | None:
  def update_environment(self, name: str, **fields) -> bool:

  # ── DOMAIN OPS ─────────────────────────────────────────────────
  def list_domains(self) -> list[dict]:
  def add_domain(self, name: str, description: str = "") -> str:

  # ── KNOWLEDGE MANAGEMENT ───────────────────────────────────────
  def list_knowledge(self, domain: str | None = None,
                     tier: str | None = None,
                     entity_id: str | None = None) -> list[dict]:
  def get_entry(self, entry_id: str) -> dict | None:
  def update_entry(self, entry_id: str, content: str) -> bool:
      """Update content + re-embed."""
  def deactivate_entry(self, entry_id: str) -> bool:
      """Soft-delete."""
  ```

- [x] 7.1.2 Implementation notes:
  - `remember()` reuses `KnowledgeRetriever.store_teaching()` dedup logic (from Phase 5.7)
  - `recall()` wraps `KnowledgeRetriever.retrieve()` but returns structured dicts, not formatted strings
  - `teach()` reuses `_classify_teaching_text()` from `conversation_handlers.py` — extract it to a shared service function first
  - `get_context()` combines environment lookup + domain filtering + entity context + RAG — same logic as the 3 call sites in handlers but packaged cleanly
- [x] 7.1.3 Extract `_classify_teaching_text` from `conversation_handlers.py` to `memory_service.py` or a shared location (both `cmd_teach` and `MemoryService.teach()` need it)
- [x] 7.1.4 Add `MemoryService` to `backend/wiring.py`:
  ```python
  def create_memory_service() -> MemoryService:
      db = create_db()
      embed = EmbeddingGateway()
      retriever = KnowledgeRetriever(db=db, embed=embed)
      return MemoryService(db=db, embed=embed, retriever=retriever)
  ```
- [x] 7.1.5 Write tests in `tests/domain/services/test_memory_service.py`:
  - `test_remember_stores_and_returns_id`
  - `test_remember_deduplicates`
  - `test_recall_returns_relevant`
  - `test_recall_with_domain_filter`
  - `test_teach_auto_classifies`
  - `test_get_context_assembles_all_layers`
  - `test_get_context_with_entity`
  - `test_entity_crud`
  - `test_environment_lookup_by_chat_id`
- [x] 7.1.6 Run `pytest` — all tests pass (1356 tests)

---

## 7.2 Refactor handlers to use MemoryService

> Bot handlers should use MemoryService instead of reaching directly into
> KnowledgeRetriever / DbGateway for memory operations.
> This keeps the brain's API surface unified.

- [x] 7.2.1 Update `handler_utils.py`:
  - Add `_memory: MemoryService` singleton alongside existing `_db`
  - Add `_get_memory() -> MemoryService` lazy getter
- [x] 7.2.2 Refactor `_resolve_environment()` (from Phase 5) to use `_memory.get_context(chat_id=...)` instead of direct DB calls
- [x] 7.2.3 Refactor `cmd_teach` to use `_memory.teach(text)` instead of direct classifier + retriever calls
- [x] 7.2.4 Refactor `_handle_nl_reply` teaching block to use `_memory.remember(...)` instead of direct `store_teaching`
- [x] 7.2.5 Refactor entity commands (Phase 6.7) to use `_memory.add_entity()`, `_memory.find_entity()`, etc.
- [x] 7.2.6 Do NOT refactor `generate_nl_reply` or `compose_request` — these are prompt assembly, not memory API
- [x] 7.2.7 Update test patches where needed
- [x] 7.2.8 Run `pytest` — all tests pass (1356 tests)

---

## 7.3 MCP Server: expose Memory API

> Thin MCP adapter that exposes MemoryService operations as MCP tools.

- [x] 7.3.1 Add `mcp` dependency to `requirements.txt` (or `pyproject.toml`)
- [x] 7.3.2 Create `mcp_server/` directory at project root:
  ```
  mcp_server/
  ├── __init__.py
  └── server.py
  ```
- [x] 7.3.3 Implement `mcp_server/server.py`:
  ```python
  from mcp import Server
  from backend.domain.services.memory_service import MemoryService
  from backend.wiring import create_memory_service

  server = Server("republic-brain")
  memory = create_memory_service()

  @server.tool("remember")
  def remember(text: str, domain: str, source: str = "mcp",
               tier: str = "specific", entity_name: str = "",
               source_url: str = "", expires_in_days: int = 0) -> dict:
      """Store knowledge in the brain.
      Args:
          text: The knowledge to store
          domain: Knowledge domain (tech_support, editorial, contractor, etc.)
          source: Where this knowledge comes from
          tier: Importance level (core, meta, specific)
          entity_name: Optional entity to link this knowledge to
          source_url: URL source for provenance
          expires_in_days: 0 = eternal, >0 = expires after N days
      Returns: {id: entry UUID, action: "created" | "updated"}
      """

  @server.tool("recall")
  def recall(query: str, domain: str = "", limit: int = 5) -> dict:
      """Retrieve relevant knowledge from the brain.
      Args:
          query: What to search for
          domain: Optional domain filter
          limit: Max results
      Returns: {results: [{id, title, content, domain, similarity}]}
      """

  @server.tool("teach")
  def teach(text: str) -> dict:
      """Teach the brain something new. Domain and tier are auto-classified.
      Returns: {id: entry UUID, domain: classified domain, tier: classified tier}
      """

  @server.tool("get_context")
  def get_context(environment: str = "", query: str = "") -> dict:
      """Get assembled context for a specific environment.
      Returns: {environment: str, knowledge: str, user_context: str}
      """

  @server.tool("list_domains")
  def list_domains() -> dict:
      """List all knowledge domains.
      Returns: {domains: [{name, description}]}
      """

  @server.tool("list_environments")
  def list_environments() -> dict:
      """List all environments.
      Returns: {environments: [{name, description, allowed_domains}]}
      """

  @server.tool("find_entity")
  def find_entity(query: str) -> dict:
      """Find an entity by name.
      Returns: {entity: {id, kind, name, summary} | null}
      """

  @server.tool("add_entity")
  def add_entity(kind: str, name: str, summary: str = "") -> dict:
      """Add a new entity to the brain.
      Returns: {id: entity UUID}
      """

  @server.tool("entity_note")
  def entity_note(entity_name: str, text: str, domain: str = "general") -> dict:
      """Store knowledge about a specific entity.
      Returns: {id: entry UUID}
      """

  @server.tool("list_knowledge")
  def list_knowledge(domain: str = "", tier: str = "") -> dict:
      """List knowledge entries with optional filters.
      Returns: {entries: [{id, tier, domain, title, content, source}]}
      """
  ```
- [x] 7.3.4 Add entry point script `mcp_server/__main__.py`:
  ```python
  from mcp_server.server import server
  server.run()
  ```
- [x] 7.3.5 Write integration tests in `tests/mcp_server/test_mcp_tools.py`:
  - Test each tool function directly (not via MCP protocol, just call the functions)
  - `test_remember_and_recall_roundtrip`
  - `test_teach_auto_classifies`
  - `test_entity_crud_via_mcp`
  - `test_list_domains`
  - `test_list_environments`
- [x] 7.3.6 Run `pytest` — all tests pass (1379 tests, 2.92s)

---

## 7.4 Claude Desktop / Claude Code integration

> Make the MCP server discoverable by Claude.

- [x] 7.4.1 Create `claude_mcp_config.json` example at project root:
  ```json
  {
    "mcpServers": {
      "republic-brain": {
        "command": "python",
        "args": ["-m", "mcp_server"],
        "cwd": "/path/to/Republic/Agent",
        "env": {
          "DATABASE_URL": "postgresql://...",
          "GEMINI_API_KEY": "..."
        }
      }
    }
  }
  ```
- [ ] 7.4.2 Test manually: run `python -m mcp_server` → server starts, accepts tool calls
- [ ] 7.4.3 Test with Claude Code: configure MCP server, verify `remember` and `recall` work

---

## 7.5 Verification

- [ ] 7.5.1 Run full `pytest` suite — all tests pass
- [ ] 7.5.2 Manual: `python -m mcp_server` → starts without errors
- [ ] 7.5.3 Manual test round-trip:
  - Call `remember("Republic публикует политическую аналитику", "editorial", source="manual")`
  - Call `recall("что публикует Republic?")` → should return the entry
- [ ] 7.5.4 Manual: verify Claude can use `recall` to answer questions about stored knowledge
- [ ] 7.5.5 Commit: `feat: add MemoryService + MCP server (brain API)`

---

## Design Notes

**Connecting a new data source (e.g., article crawler):**
```python
# crawler.py — just uses the memory API
from backend.domain.services.memory_service import MemoryService
memory = MemoryService()

for article in crawl_articles():
    memory.remember(
        text=article.summary,
        domain="editorial",
        source="article_crawler",
        source_url=article.url,
        expires_at=None,
    )
```
Zero schema changes. Zero new endpoints. The crawler just calls `remember()`.

**Connecting via MCP (external agent):**
```
User: "What do we know about our competitors?"
Claude → MCP tool call: recall(query="competitors", domain="competitors")
Claude → receives: [{title: "Медуза", content: "Основной конкурент..."}]
Claude → responds with synthesized answer
```

**API surface summary:**

| Operation | Write | Read | What it does |
|-----------|-------|------|-------------|
| `remember` | x | | Store knowledge (dedup-aware) |
| `recall` | | x | Retrieve by semantic similarity |
| `teach` | x | | Classify + store (domain/tier auto) |
| `get_context` | | x | Full prompt context assembly |
| `add_entity` | x | | Create entity |
| `find_entity` | | x | Lookup entity |
| `entity_note` | x | | Store entity-linked knowledge |
| `list_*` | | x | Enumerate domains/environments/knowledge/entities |
| `update_entry` | x | | Edit existing knowledge |
| `deactivate_entry` | x | | Soft-delete knowledge |
