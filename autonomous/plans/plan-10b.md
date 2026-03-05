# Plan 10b: Infrastructure Memory + Commands Structure

## Context

This plan reorganizes the codebase: memory/knowledge services move under `infrastructure/memory/` (shared data-access), solid use-case logic moves into `commands/` (one file/dir per command), and LLM orchestration logic gets extracted into `brain/dynamic/` as BaseGenAI implementations.

Key principle: `brain/dynamic/` holds anything that calls an LLM via BaseGenAI. `commands/` holds solid (deterministic) logic. `infrastructure/memory/` holds shared data access.

After this phase, all code lives in its new location. Old `domain/` files get compatibility stubs. Controllers are NOT yet wired (that's plan 10c).

## Step 1: Create `infrastructure/memory/` ✅ DONE (Session 2)

Move these services — they are shared data-access used across many commands:

| Source | Destination | Changes |
|---|---|---|
| `backend/domain/services/memory_service.py` | `backend/infrastructure/memory/memory_service.py` | Remove `classify_teaching()` method (uses LLM — extracted to brain/dynamic). Remove `_gemini` from constructor. Keep remember/recall/teach (teach now requires domain+tier as params), entity CRUD, environment CRUD. |
| `backend/domain/services/knowledge_retriever.py` | `backend/infrastructure/memory/retriever.py` | No changes, just move. |
| `backend/domain/services/admin_service.py` | `backend/infrastructure/memory/admin.py` | No changes, just move. |
| `backend/domain/services/support_user_lookup.py` | `backend/infrastructure/memory/user_lookup.py` | No changes, just move. |
| (new) | `backend/infrastructure/memory/__init__.py` | Re-export: `MemoryService`, `KnowledgeRetriever`, `AdminService`, `SupportUserLookup` |

### MemoryService changes in detail

The `classify_teaching()` method (lines ~84-105) uses `compose_request` and `self._gemini` to call an LLM. Extract this into `brain/dynamic/classify_teaching.py`. The moved `MemoryService` keeps `teach()` but now requires `domain` and `tier` as parameters (no auto-classification). The controller layer calls the dynamic classifier first, then calls `memory.teach()`.

Remove `_gemini` dependency from constructor (was only used by `classify_teaching()`).

## Step 2: Create `brain/dynamic/` implementations

Each file extends `BaseGenAI` and wraps one LLM operation. Extract from current services:

| New file | Source | What it does |
|---|---|---|
| `brain/dynamic/classify_teaching.py` | `memory_service.py:classify_teaching()` + `compose_request.classify_teaching()` | Classify text into domain+tier. Model: gemini-2.5-flash. Template: `knowledge/classify-teaching.md` |
| `brain/dynamic/conversation_reply.py` | `conversation_service.py:generate_nl_reply()` (lines 70-134) + `compose_request.conversation_reply()` | Generate NL reply with RAG+DB context. Model: gemini-3-flash-preview. Template: `chat/conversation.md` |
| `brain/dynamic/tech_support.py` | `tech_support_handler.py:draft_reply()` + `compose_request.support_email()` + `compose_request.support_triage()` | Draft support answers. Two LLM calls: triage (gemini-2.5-flash, `email/support-triage.md`) then draft (gemini-3-flash-preview, `email/support-email.md`) |
| `brain/dynamic/query_db.py` | `query_tool.py:query()` (lines 28-53) | NL to SQL + execute. Model: gemini-3-flash-preview. Template: `db-query/compose-query.md` |
| `brain/dynamic/tool_routing.py` | `tool_router.py:route()` (lines 27-49) | Decide which tools (rag/republic_db/redefine_db) to use. Template: `chat/require-tools.md` |
| `brain/dynamic/inbox_classify.py` | `inbox_service.py:_llm_classify()` (lines 49-60) + `compose_request.inbox_classify()` | Classify incoming email. Model: gemini-2.5-flash. Template: `email/inbox-classify.md` |
| `brain/dynamic/support_draft.py` | `inbox_service.py:_handle_support()` | Thin wrapper delegating to tech_support dynamic |
| `brain/dynamic/editorial_assess.py` | `inbox_service.py:_handle_editorial()` (lines 74-94) + `compose_request.editorial_assess()` | Assess editorial email. Model: gemini-3-flash-preview. Template: `email/editorial-assess.md` |
| `brain/dynamic/summarize_article.py` | `ingest_articles.py:_summarize()` (lines 50-58) | Summarize article. Model: gemini-2.5-flash. Template: `knowledge/summarize-article.md` |
| `brain/dynamic/extract_knowledge.py` | `extract_conversation_knowledge.py:_extract_facts()` (lines 56-66) | Extract facts from conversations. Template: `knowledge/extract-facts.md` |
| `brain/dynamic/scrape_competitors.py` | `scrape_competitors.py:_summarize()` (lines 56-65) | Summarize competitor content. Template: `knowledge/summarize-competitor.md` |
| `brain/dynamic/contractor_parse.py` | `compose_request.contractor_parse()` + facade `parse_contractor_data()` | Parse free-form contractor data. Model: gemini-2.5-flash. Template: `contractor/contractor-parse.md` |

### Example: `brain/dynamic/conversation_reply.py`

```python
class ConversationReply(BaseGenAI):
    """Generate NL reply using RAG context + optional DB queries."""

    def __init__(self, gemini, retriever, tool_router=None, query_tools=None):
        super().__init__(gemini)
        self._retriever = retriever
        self._tool_router = tool_router  # another BaseGenAI
        self._query_tools = query_tools
        self._model = "gemini-3-flash-preview"

    def _pick_template(self, input, context) -> str:
        return "chat/conversation.md"

    def _build_context(self, input, context) -> dict:
        # RAG retrieval, tool routing (may call self._tool_router.run()),
        # DB queries — all assembled here
        ...
        return {"VERBOSE": ..., "ENVIRONMENT": ..., "USER_CONTEXT": ...,
                "KNOWLEDGE": ..., "CONVERSATION": ..., "MESSAGE": input}

    def _parse_response(self, raw) -> dict:
        return {"reply": raw.get("reply", str(raw))}
```

Note: `_build_context` calls `self._tool_router.run()` which is itself a BaseGenAI — this is the natural recursion.

### Example: `brain/dynamic/classify_teaching.py`

```python
class ClassifyTeaching(BaseGenAI):
    def __init__(self, gemini, db, embed):
        super().__init__(gemini)
        self._db = db
        self._embed = embed
        self._model = "gemini-2.5-flash"

    def _pick_template(self, input, context) -> str:
        return "knowledge/classify-teaching.md"

    def _build_context(self, input, context) -> dict:
        # Find similar entries, list known domains
        # Same logic as old memory_service.classify_teaching()
        ...

    def _parse_response(self, raw) -> dict:
        return {"domain": raw.get("domain", "general"), "tier": raw.get("tier", "specific")}
```

## Step 3: Create `backend/commands/`

Each command file contains solid (non-LLM) logic. Controllers not yet wired (plan 10c). This step moves deterministic use-case code.

| New file | Source(s) | Contents |
|---|---|---|
| `commands/__init__.py` | (new) | Empty |
| `commands/conversation.py` | `conversation_service.py` | Solid helpers: `build_conversation_context()` (lines 18-51), `format_reply_chain()`. Controller stub. |
| `commands/support.py` | `tech_support_handler.py` | Solid parts: `_format_thread()`, `save_outbound()`, `discard()`, thread management. Controller stub. |
| `commands/code.py` | `domain/use_cases/run_claude_code.py` | Move entire file. Pure subprocess logic. |
| `commands/health.py` | `domain/use_cases/check_health.py` | Move entire file. Pure HTTP/kubectl checks. |
| `commands/teach.py` | (new, thin) | Controller stub. No solid logic. |
| `commands/search.py` | (new, thin) | Controller stub. Retriever is in infrastructure/memory. |
| `commands/query.py` | (new, thin) | Controller stub. |
| `commands/ingest.py` | `domain/use_cases/ingest_articles.py` | Move solid orchestration loop. LLM summarization in `brain/dynamic/summarize_article.py`. |
| `commands/knowledge_extract.py` | `domain/use_cases/extract_conversation_knowledge.py` + `run_knowledge_pipelines.py` | Move solid orchestration. LLM extraction in `brain/dynamic/extract_knowledge.py`. |
| `commands/inbox.py` | `domain/services/inbox_service.py` | Move approval workflow state: `_pending_support`, `_pending_editorial`, `approve_support()`, `skip_support()`, `approve_editorial()`, `skip_editorial()`, `fetch_unread()`, `idle_wait()`. LLM classify/assess in brain/dynamic/. |
| `commands/scrape.py` | `domain/use_cases/scrape_competitors.py` | Move solid orchestration. LLM in `brain/dynamic/scrape_competitors.py`. |
| `commands/invoice/__init__.py` | (new) | Controller + preparer stubs. |
| `commands/invoice/generate.py` | `domain/use_cases/generate_invoice.py` | Move entire file. |
| `commands/invoice/batch.py` | `domain/use_cases/generate_batch_invoices.py` | Move entire file. |
| `commands/invoice/prepare.py` | `domain/use_cases/prepare_invoice.py` | Move entire file. |
| `commands/invoice/resolve_amount.py` | `domain/use_cases/resolve_amount.py` | Move entire file. |
| `commands/budget/__init__.py` | (new) | Controller + preparer stubs. |
| `commands/budget/compute.py` | `domain/use_cases/compute_budget.py` | Move entire file. |
| `commands/budget/redirect.py` | `domain/services/budget_service.py` | Move entire file. |
| `commands/contractor/__init__.py` | (new) | Controller + preparer stubs. |
| `commands/contractor/validate.py` | `domain/use_cases/validate_contractor.py` | Move entire file. |
| `commands/contractor/create.py` | `domain/services/contractor_service.py` | Move `create_contractor()`, `check_registration_complete()`. LLM parsing via `brain/dynamic/contractor_parse.py`. |
| `commands/contractor/sync_entities.py` | `domain/use_cases/sync_contractor_entities.py` | Move entire file. |
| `commands/bank/__init__.py` | (new) | Controller + preparer stubs. |
| `commands/bank/parse_statement.py` | `domain/use_cases/parse_bank_statement.py` | Move entire file. |

## Step 4: Add compatibility re-exports in old locations

For each moved file, leave a stub that re-imports from the new location. Prevents breaking existing imports during transition:

```python
# backend/domain/services/memory_service.py (stub)
from backend.infrastructure.memory.memory_service import MemoryService  # noqa: F401
```

Do this for ALL moved files. Keeps existing tests and telegram_bot imports working until plan 10d cleans them up.

## Step 5: Remove `compose_request.py` (distribute)

`compose_request.py` is the central prompt hub. Its functions map 1:1 to brain/dynamic implementations:

| compose_request function | Absorbed into |
|---|---|
| `classify_command()` | `brain/router.py` (done in 10a) |
| `conversation_reply()` | `brain/dynamic/conversation_reply.py` |
| `tech_support_question()` | `brain/dynamic/tech_support.py` |
| `support_email()` | `brain/dynamic/tech_support.py` |
| `support_triage()` | `brain/dynamic/tech_support.py` |
| `classify_teaching()` | `brain/dynamic/classify_teaching.py` |
| `inbox_classify()` | `brain/dynamic/inbox_classify.py` |
| `editorial_assess()` | `brain/dynamic/editorial_assess.py` |
| `contractor_parse()` | `brain/dynamic/contractor_parse.py` |
| `translate_name()` | Keep in `commands/contractor/create.py` or small dynamic |

The `_MODELS` dict is distributed — each brain/dynamic class knows its own model. The `_retriever` global is gone — retriever injected via constructor.

Leave a stub `compose_request.py` that re-exports from new locations.

## Verification Checklist

- [ ] `from backend.infrastructure.memory import MemoryService, KnowledgeRetriever, SupportUserLookup` works
- [ ] `from backend.infrastructure.memory.admin import classify_draft_reply` works
- [ ] `from backend.brain.dynamic.conversation_reply import ConversationReply` works
- [ ] `from backend.brain.dynamic.classify_teaching import ClassifyTeaching` works
- [ ] `ConversationReply` extends `BaseGenAI`
- [ ] `ClassifyTeaching` extends `BaseGenAI`
- [ ] All 12 brain/dynamic files extend `BaseGenAI`
- [ ] `from backend.commands.health import ...` works (check_health moved)
- [ ] `from backend.commands.code import ...` works (run_claude_code moved)
- [ ] `from backend.commands.invoice.generate import ...` works
- [ ] `from backend.commands.budget.compute import ...` works
- [ ] Old imports still work via stubs: `from backend.domain.services.memory_service import MemoryService`
- [ ] All existing tests still pass (stubs ensure import compatibility)
- [ ] No brain/dynamic class imports from `domain/services/compose_request` directly
- [ ] MemoryService no longer has `_gemini` dependency
- [ ] MemoryService.teach() requires domain+tier parameters
