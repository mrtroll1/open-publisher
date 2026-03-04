# Phase 8: Active Knowledge Agents

> The brain starts actively acquiring knowledge instead of passively waiting for teachings.
> Crawlers, summarizers, and knowledge pipelines feed into the same MemoryService API.
>
> Polar: (a) every knowledge pipeline is a standalone script that calls `memory.remember()` —
> adding a new pipeline = one new file, zero changes to existing code.
> (b) pipelines are idempotent — re-running them updates existing entries, never duplicates.

## 8.0 Pre-flight

- [x] 8.0.1 Confirm Phases 5-7 are complete (environments, entities, MemoryService, MCP)
- [x] 8.0.2 Verify `memory.remember()` deduplication works (similarity > 0.90 → update)
- [x] 8.0.3 Verify `source_url` dedup path works (same URL → update, not insert) — NOT present yet, added in 8.1
- [x] 8.0.4 Run `pytest` — all tests pass (baseline: 1379 tests)

---

## 8.1 Source-URL deduplication

> Before building crawlers, ensure `remember()` can dedup by URL (not just embedding similarity).
> A crawler re-visiting the same page should update the existing entry, not create a new one.

- [x] 8.1.1 Add method to `KnowledgeRepo`:
  ```python
  def find_by_source_url(self, source_url: str) -> dict | None:
      """Find active knowledge entry by source_url. Returns most recent if multiple."""
  ```
- [x] 8.1.2 Update `MemoryService.remember()`:
  - If `source_url` is provided, check `find_by_source_url` first
  - If found, update content + re-embed (idempotent re-crawl)
  - If not found, fall through to embedding dedup, then insert
- [x] 8.1.3 Add index:
  ```sql
  CREATE INDEX IF NOT EXISTS idx_knowledge_source_url
      ON knowledge_entries(source_url) WHERE source_url IS NOT NULL;
  ```
- [x] 8.1.4 Write tests:
  - `test_remember_with_source_url_deduplicates`
  - `test_remember_source_url_updates_content`
  - `test_remember_different_urls_creates_separate`
- [x] 8.1.5 Run `pytest` — all tests pass

---

## 8.2 Article ingestion pipeline

> Reads Republic articles (via existing infrastructure) and stores summaries
> as knowledge entries. Each article becomes a `specific` entry in `editorial` domain.

- [x] 8.2.1 Create `backend/domain/use_cases/ingest_articles.py`:
  ```python
  class IngestArticles:
      """Fetch recent articles, summarize via LLM, store in brain."""

      def __init__(self, memory: MemoryService, gemini: GeminiGateway | None = None):
          self._memory = memory
          self._gemini = gemini or GeminiGateway()

      def execute(self, articles: list[dict], domain: str = "editorial") -> list[str]:
          """Process articles. Returns list of entry UUIDs (created or updated)."""
          entry_ids = []
          for article in articles:
              summary = self._summarize(article)
              entry_id = self._memory.remember(
                  text=summary,
                  domain=domain,
                  source="article_ingest",
                  source_url=article.get("url", ""),
                  tier="specific",
              )
              entry_ids.append(entry_id)
          return entry_ids

      def _summarize(self, article: dict) -> str:
          """LLM-summarize article to ~200 words."""
          prompt = load_template("summarize-article.md", {
              "TITLE": article["title"],
              "CONTENT": article["content"][:8000],
          })
          result = self._gemini.call(prompt)
          return result.get("summary", article["title"])
  ```
- [x] 8.2.2 Create `templates/summarize-article.md`:
  ```markdown
  Суммаризируй статью для внутренней базы знаний редакции.
  Сохрани ключевые факты, имена, цифры. Максимум 200 слов.

  ## Заголовок
  {{TITLE}}

  ## Текст
  {{CONTENT}}

  Верни JSON: {"summary": "<суммари>"}
  ```
- [x] 8.2.3 Add admin command `/ingest_articles [month]` that fetches articles and runs pipeline
- [x] 8.2.4 Write tests:
  - `test_ingest_creates_entries`
  - `test_ingest_updates_existing_by_url`
  - `test_ingest_summarizes_via_llm`
- [x] 8.2.5 Run `pytest` — all tests pass (1402 tests)

---

## 8.3 Competitor scraper pipeline (skeleton)

> Architecture-ready skeleton for scraping competitor content.
> Same pattern as article ingestion: crawl → summarize → `memory.remember()`.

- [x] 8.3.1 Create `backend/domain/use_cases/scrape_competitors.py`:
  ```python
  class ScrapeCompetitors:
      """Scrape competitor websites, store observations in brain."""

      def __init__(self, memory: MemoryService, gemini: GeminiGateway | None = None):
          self._memory = memory
          self._gemini = gemini or GeminiGateway()

      def execute(self, sources: list[dict]) -> list[str]:
          """Process competitor sources.
          Each source: {name: str, url: str, content: str}
          Returns list of entry UUIDs."""
          entry_ids = []
          for source in sources:
              # Find or create competitor entity
              entity = self._memory.find_entity(query=source["name"])
              if not entity:
                  entity_id = self._memory.add_entity(
                      kind="competitor", name=source["name"],
                  )
              else:
                  entity_id = entity["id"]

              summary = self._summarize(source)
              entry_id = self._memory.remember(
                  text=summary,
                  domain="competitors",
                  source="competitor_scraper",
                  source_url=source["url"],
                  entity_id=entity_id,
                  tier="specific",
              )
              entry_ids.append(entry_id)
          return entry_ids

      def _summarize(self, source: dict) -> str:
          """LLM-summarize competitor content."""
          prompt = load_template("summarize-competitor.md", {
              "NAME": source["name"],
              "URL": source["url"],
              "CONTENT": source["content"][:8000],
          })
          result = self._gemini.call(prompt)
          return result.get("summary", f"{source['name']}: {source['url']}")
  ```
- [x] 8.3.2 Create `templates/summarize-competitor.md`
- [x] 8.3.3 Ensure `competitors` domain exists: auto-created via `memory.add_domain()` in `execute()`
- [x] 8.3.4 Write tests (mock the LLM, verify remember calls):
  - `test_scrape_creates_entity_and_knowledge`
  - `test_scrape_reuses_existing_entity`
  - `test_scrape_updates_by_source_url`
- [x] 8.3.5 Run `pytest` — all tests pass (1402 tests)

---

## 8.4 Conversation summary extraction

> Periodically extract key facts from conversation history into knowledge entries.
> This is the "learn from conversations" pathway.

- [x] 8.4.1 Create `backend/domain/use_cases/extract_conversation_knowledge.py`:
  ```python
  class ExtractConversationKnowledge:
      """Extract memorable facts from recent conversations, store in brain."""

      def __init__(self, memory: MemoryService, db: DbGateway,
                   gemini: GeminiGateway | None = None):
          self._memory = memory
          self._db = db
          self._gemini = gemini or GeminiGateway()

      def execute(self, chat_id: int, since_hours: int = 24,
                  environment: str | None = None) -> list[str]:
          """Extract knowledge from recent conversations in a chat.
          Returns list of new entry UUIDs."""
          messages = self._db.get_recent_conversations(chat_id, hours=since_hours)
          if len(messages) < 3:
              return []  # too few messages to extract from

          transcript = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
          facts = self._extract_facts(transcript)

          entry_ids = []
          for fact in facts:
              domain = fact.get("domain", "general")
              entry_id = self._memory.remember(
                  text=fact["text"],
                  domain=domain,
                  source="conversation_extract",
                  tier="specific",
              )
              entry_ids.append(entry_id)
          return entry_ids

      def _extract_facts(self, transcript: str) -> list[dict]:
          """LLM extracts memorable facts from transcript."""
          prompt = load_template("extract-facts.md", {"TRANSCRIPT": transcript})
          result = self._gemini.call(prompt)
          return result.get("facts", [])
  ```
- [x] 8.4.2 Add `get_recent_conversations` method to `ConversationRepo`:
  ```python
  def get_recent_conversations(self, chat_id: int, hours: int = 24) -> list[dict]:
      """Fetch conversations from last N hours for a chat."""
  ```
- [x] 8.4.3 Create `templates/extract-facts.md`:
  ```markdown
  Извлеки запоминающиеся факты из переписки.
  Это НЕ пересказ — только конкретные факты, решения, предпочтения, инструкции.
  Пропусти тривиальные сообщения (приветствия, подтверждения, команды).
  Если ничего запоминающегося нет — верни пустой список.

  ## Переписка
  {{TRANSCRIPT}}

  Верни JSON: {"facts": [{"text": "<факт>", "domain": "<домен>"}]}
  Домены: tech_support, editorial, contractor, payments, identity, general
  ```
- [x] 8.4.4 Add admin command `/extract_knowledge [hours]` — runs extraction on current chat
- [x] 8.4.5 Write tests:
  - `test_extract_stores_facts`
  - `test_extract_skips_short_conversations`
  - `test_extract_deduplicates_via_remember`
- [x] 8.4.6 Run `pytest` — all tests pass

---

## 8.5 Scheduled pipeline runner

> Pipelines run on a schedule (or can be triggered manually).
> Keep it simple: a cron-like background task in the bot, not a separate service.

- [x] 8.5.1 Create `backend/domain/use_cases/run_knowledge_pipelines.py`:
  ```python
  async def run_scheduled_pipelines(memory: MemoryService, db: DbGateway):
      """Run all scheduled knowledge pipelines. Called periodically."""
      # 1. Extract conversation knowledge from active environments
      environments = db.list_environments()
      extractor = ExtractConversationKnowledge(memory, db)
      for env in environments:
          bindings = db.get_environment_bindings(env["name"])
          for binding in bindings:
              extractor.execute(binding["chat_id"], since_hours=24, environment=env["name"])

      # 2. Future: article ingestion, competitor scraping, etc.
      # Each pipeline is a simple function call to execute()
  ```
- [x] 8.5.2 Already existed as `get_bindings_for_environment` in `EnvironmentRepo`
- [x] 8.5.3 Wire into bot's background tasks (alongside `email_listener_task` in `main.py`):
  ```python
  async def knowledge_pipeline_task():
      """Run knowledge pipelines every 6 hours."""
      memory = create_memory_service()
      db = create_db()
      while True:
          try:
              await asyncio.to_thread(run_scheduled_pipelines, memory, db)
          except Exception:
              logger.exception("Knowledge pipeline failed")
          await asyncio.sleep(6 * 3600)  # every 6 hours
  ```
- [x] 8.5.4 Write tests
- [x] 8.5.5 Run `pytest` — all tests pass

---

## 8.6 Conversation history safety valve

> Simple truncation for long conversations. No LLM summarization — just keep
> recent N messages and note how many were omitted.

- [x] 8.6.1 Update `build_conversation_context()` in `conversation_service.py`:
  - Added `max_verbatim: int = 8` parameter
  - Long chains truncated to last N messages with `[{skipped} предыдущих сообщений опущено]` header
  - Updated `get_reply_chain` call to `depth=20`
- [x] 8.6.2 Update `get_reply_chain` depth from 10 to 20 (since we now truncate ourselves)
- [x] 8.6.3 Write tests:
  - `test_long_chain_truncated`
  - `test_short_chain_not_truncated`
  - `test_truncation_preserves_recent_messages`
- [x] 8.6.4 Run `pytest` — all tests pass

---

## 8.7 RAG similarity threshold

> Filter out low-relevance results to reduce noise.

- [x] 8.7.1 Update `KnowledgeRetriever.retrieve()`:
  - Added `min_similarity: float = 0.3` parameter
  - Filters entries with `similarity < min_similarity` after DB query
- [x] 8.7.2 Write tests:
  - `test_retrieve_filters_low_similarity`
  - `test_retrieve_keeps_high_similarity`
- [x] 8.7.3 Run `pytest` — all tests pass

---

## 8.8 Verification

- [x] 8.8.1 Run full `pytest` suite — all tests pass (1413 tests)
8.8.2 Manual: `/ingest_articles` → articles stored as knowledge entries
8.8.3 Manual: `/extract_knowledge 48` → facts extracted from recent conversations
8.8.4 Manual: ask bot about recently ingested article content → should retrieve via RAG
8.8.5 Manual: verify low-similarity RAG results are filtered out
- [x] 8.8.6 Commit: `feat: add knowledge pipelines + conversation safety valve + RAG threshold`

---

## Design Notes

**Adding a new knowledge pipeline:**
1. Create `backend/domain/use_cases/my_new_pipeline.py`
2. Implement `execute()` that calls `memory.remember()` for each piece of knowledge
3. Optionally add to `run_scheduled_pipelines()` for automatic execution
4. Optionally add an admin command for manual triggering
5. Done. Zero changes to DB schema, zero changes to retrieval logic, zero changes to MCP server.

**Pipeline idempotency:**
- URL-based sources: `source_url` dedup ensures re-crawling updates, not duplicates
- Text-based sources: embedding similarity > 0.90 dedup prevents near-duplicate accumulation
- Both mechanisms are in `MemoryService.remember()` — pipelines get this for free

**Knowledge lifecycle:**
```
Source → Pipeline → remember() → knowledge_entries → retrieve()/recall() → prompt
  │                    │                 │
  │              dedup check        expires_at filter
  │              source_url check   similarity threshold
  │                                 domain filter
  │
  ├── Article crawler      → domain: editorial
  ├── Competitor scraper   → domain: competitors, entity_id: competitor entity
  ├── Conversation extract → domain: varies, source: conversation_extract
  ├── Admin /teach         → domain: auto-classified, source: admin_teach
  ├── MCP remember()       → domain: caller-specified, source: mcp
  └── Future: social media → domain: smm, source: social_scraper
```
