# Plan 10d: API Layer + Telegram Refactor + Cleanup

## Context

Final phase. Adds a FastAPI layer over Brain, refactors telegram bot to be a thin HTTP client, and cleans up all dead code (removing `domain/` entirely).

After this phase: backend runs as a separate uvicorn process, telegram bot calls it via HTTP, and the old `domain/` directory is gone.

## Progress

- [x] Step 1: Create `backend/api.py` — FastAPI Application
- [x] Step 2: Create `backend/run.py` — Uvicorn Entrypoint
- [x] Step 3: Create `telegram_bot/backend_client.py` — HTTP Client
- [x] Step 4: Refactor `telegram_bot/handler_utils.py`
- [x] Step 5: Refactor Telegram Handlers
- [ ] Step 6: Delete `domain/` Directory
- [ ] Step 7: Update `backend/__init__.py` (Facade)
- [ ] Step 8: Update Tests
- [x] Step 9: Config + Deployment (config part — BACKEND_URL, requirements.txt)

## Step 1: Create `backend/api.py` — FastAPI Application

```python
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any
from backend.wiring import create_brain

app = FastAPI(title="Republic Agent Backend")
brain = create_brain()

class ProcessRequest(BaseModel):
    input: str
    environment_id: str = "default"
    user_id: str = ""

class CommandRequest(BaseModel):
    command: str
    args: str = ""
    environment_id: str = "default"
    user_id: str = ""

class BrainResponse(BaseModel):
    result: Any
    error: str = ""

@app.post("/brain/process")
def process(req: ProcessRequest) -> BrainResponse:
    try:
        result = brain.process(req.input, req.environment_id, req.user_id)
        return BrainResponse(result=result)
    except Exception as e:
        return BrainResponse(result=None, error=str(e))

@app.post("/brain/command")
def command(req: CommandRequest) -> BrainResponse:
    try:
        result = brain.process_command(req.command, req.args, req.environment_id, req.user_id)
        return BrainResponse(result=result)
    except Exception as e:
        return BrainResponse(result=None, error=str(e))
```

Additional endpoints needed for stateful operations:

```python
# Inbox approval workflows
POST /inbox/approve-support    {uid}
POST /inbox/skip-support       {uid}
POST /inbox/approve-editorial  {uid}
POST /inbox/skip-editorial     {uid}
POST /inbox/fetch-unread

# Memory management
POST /memory/teach             {text, domain, tier}
GET  /memory/search            {query, domain}
GET  /memory/entry/{entry_id}
PUT  /memory/entry/{entry_id}  {text, ...}
DELETE /memory/entry/{entry_id}
GET  /memory/domains
GET  /memory/environments

# Entity management
POST /entity/add               {kind, name, ...}
GET  /entity/find              {query}
POST /entity/{id}/note         {text}
```

## Step 2: Create `backend/run.py` — Uvicorn Entrypoint

```python
import uvicorn
if __name__ == "__main__":
    uvicorn.run("backend.api:app", host="0.0.0.0", port=8100, reload=False)
```

## Step 3: Create `telegram_bot/backend_client.py` — HTTP Client

Thin async HTTP client replacing direct backend imports.

```python
import httpx
from common.config import BACKEND_URL  # e.g., "http://localhost:8100"

_client = httpx.AsyncClient(base_url=BACKEND_URL, timeout=120.0)

async def process(input: str, environment_id: str, user_id: str) -> dict:
    resp = await _client.post("/brain/process", json={
        "input": input, "environment_id": environment_id, "user_id": user_id
    })
    return resp.json()

async def command(cmd: str, args: str, environment_id: str, user_id: str) -> dict:
    resp = await _client.post("/brain/command", json={
        "command": cmd, "args": args,
        "environment_id": environment_id, "user_id": user_id
    })
    return resp.json()

async def teach(text: str, domain: str = "", tier: str = "") -> dict: ...
async def search(query: str, domain: str = "") -> dict: ...
async def approve_support(uid: str) -> dict: ...
async def skip_support(uid: str) -> dict: ...
# ... etc for all API endpoints
```

## Step 4: Refactor `telegram_bot/handler_utils.py`

Remove all direct backend imports and module-level singletons.

**Remove (currently lines ~12-25):**
```python
from backend.wiring import create_db, create_inbox_service, ...
from backend.domain.services.compose_request import set_retriever, _get_retriever
_db = create_db()
_inbox = create_inbox_service()
_memory = create_memory_service()
set_retriever(create_knowledge_retriever())
_query_tools = create_query_tools()
_tool_router = create_tool_router(_query_tools) if _query_tools else None
```

**Replace with:**
```python
from telegram_bot import backend_client
```

`resolve_environment` and `resolve_entity_context` now call API instead of direct memory access.

Keep: `ThinkingMessage`, `_send_html`, `_send`, `_save_turn` (may need lightweight DB for conversation logging), `_parse_flags`, `parse_month_arg`, `parse_date_range_arg`.

## Step 5: Refactor Telegram Handlers

### `conversation_handlers.py`
- `cmd_nl`: Replace `generate_nl_reply(...)` → `await backend_client.process(text, str(chat_id), str(user_id))`
- `_handle_nl_reply`: Same replacement
- `cmd_teach`: Replace `_memory.teach(...)` → `await backend_client.teach(text)`
- `cmd_ksearch`: Replace `retriever.retrieve(...)` → `await backend_client.search(query)`
- `cmd_knowledge`, `cmd_forget`, `cmd_kedit`: Use memory API endpoints

### `support_handlers.py`
- `cmd_support`: Replace `compose_request + gemini.call()` → `await backend_client.command("support", text, ...)`
- `cmd_health`: Replace `run_healthchecks()` → `await backend_client.command("health", "", ...)`
- `cmd_code`: Replace `run_claude_code(...)` → `await backend_client.command("code", text, ...)`
- `handle_support_callback`, `handle_editorial_callback`: Use inbox API endpoints

### `admin_handlers.py`
- `cmd_budget`: Replace `ComputeBudget().execute(month)` → `await backend_client.command("budget", month, ...)`
- `cmd_generate`: Keep multi-step flow but use API for generation
- `cmd_ingest_articles`: Replace direct call → `await backend_client.command("ingest", args, ...)`
- `cmd_sync_entities`: → API call
- `cmd_extract_knowledge`: → API call

### `telegram_bot/router.py`
- Remove `from backend.domain.services.command_classifier import CommandClassifier`
- Group NL classification now → `await backend_client.process(text, str(chat_id), str(user_id))` — Brain handles classification + routing internally
- Simplify `_route_group` / `handle_group_message` — brain does the routing

## Step 6: Delete `domain/` Directory

Remove entire tree:

```
backend/domain/
  __init__.py
  services/
    compose_request.py           → distributed into brain/dynamic/
    command_classifier.py        → brain/router.py
    conversation_service.py      → brain/dynamic/conversation_reply.py + commands/conversation.py
    memory_service.py            → infrastructure/memory/memory_service.py
    knowledge_retriever.py       → infrastructure/memory/retriever.py
    support_user_lookup.py       → infrastructure/memory/user_lookup.py
    admin_service.py             → infrastructure/memory/admin.py
    tech_support_handler.py      → commands/support.py + brain/dynamic/tech_support.py
    inbox_service.py             → commands/inbox.py + brain/dynamic/
    tool_router.py               → brain/dynamic/tool_routing.py
    query_tool.py                → brain/dynamic/query_db.py
    contractor_service.py        → commands/contractor/
    invoice_service.py           → commands/invoice/
    budget_service.py            → commands/budget/redirect.py
  use_cases/
    check_health.py              → commands/health.py
    run_claude_code.py           → commands/code.py
    generate_invoice.py          → commands/invoice/generate.py
    generate_batch_invoices.py   → commands/invoice/batch.py
    prepare_invoice.py           → commands/invoice/prepare.py
    resolve_amount.py            → commands/invoice/resolve_amount.py
    compute_budget.py            → commands/budget/compute.py
    parse_bank_statement.py      → commands/bank/parse_statement.py
    validate_contractor.py       → commands/contractor/validate.py
    sync_contractor_entities.py  → commands/contractor/sync_entities.py
    ingest_articles.py           → commands/ingest.py
    extract_conversation_knowledge.py → commands/knowledge_extract.py
    run_knowledge_pipelines.py   → commands/knowledge_extract.py
    scrape_competitors.py        → commands/scrape.py
```

## Step 7: Update `backend/__init__.py` (Facade)

Rewrite to expose Brain API:

```python
"""Backend facade."""
from backend.brain import Brain
from backend.wiring import create_brain
```

Only re-export what telegram bot still needs directly (should be minimal after API refactor).

## Step 8: Update Tests

Move test files to match new structure:

| Old test path | New test path |
|---|---|
| `tests/domain/services/test_conversation_service.py` | `tests/brain/dynamic/test_conversation_reply.py` |
| `tests/domain/services/test_command_classifier.py` | `tests/brain/test_router.py` |
| `tests/domain/services/test_memory_service.py` | `tests/infrastructure/memory/test_memory_service.py` |
| `tests/domain/services/test_knowledge_retriever.py` | `tests/infrastructure/memory/test_retriever.py` |
| `tests/domain/services/test_tech_support_handler.py` | `tests/commands/test_support.py` |
| `tests/domain/services/test_inbox_service.py` | `tests/commands/test_inbox.py` |
| `tests/domain/use_cases/test_generate_invoice.py` | `tests/commands/invoice/test_generate.py` |
| `tests/domain/use_cases/test_compute_budget.py` | `tests/commands/budget/test_compute.py` |
| `tests/domain/use_cases/test_parse_bank_statement.py` | `tests/commands/bank/test_parse_statement.py` |

Update all `from backend.domain.*` imports to new locations.

## Step 9: Config + Deployment

Add to `common/config.py`:
```python
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8100")
```

Add `fastapi`, `uvicorn`, `httpx` to `requirements.txt`.

Update process manager / docker-compose to start backend as separate service.

## Verification Checklist

- [ ] `uvicorn backend.api:app` starts without errors
- [ ] `POST /brain/process {"input": "привет"}` returns a reply
- [ ] `POST /brain/command {"command": "health"}` returns healthcheck results
- [ ] Telegram bot starts and connects to API
- [ ] `/health` via telegram works end-to-end
- [ ] `/support question` via telegram works end-to-end
- [ ] `/nl question` via telegram works end-to-end
- [ ] Group chat NL messages route correctly through API
- [ ] Contractor FSM still works (stays in telegram, not routed through Brain)
- [ ] `backend/domain/` directory is completely deleted
- [ ] `grep -r "backend.domain" .` returns zero results (no remaining imports)
- [ ] All tests pass with updated imports
- [ ] `_admin_reply_map`, `_support_draft_map`, `_kedit_pending` stay in telegram bot
- [ ] Email inbox listener uses API endpoints
- [ ] No module-level singleton instantiation in handler_utils.py
- [ ] Backend and telegram bot can be started/stopped independently
