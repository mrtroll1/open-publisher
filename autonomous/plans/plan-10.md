# Brain Architecture Refactor

## Context

The codebase works but lacks unifying abstractions. Tracing a pipeline requires keeping too many specifics in mind. The goal: introduce a small set of template-method abstractions (Brain, Authorizer, Router, BaseController, BaseGenAI) so every flow follows the same pattern, and switching any component from solid to dynamic requires minimal change.

Currently: telegram bot imports backend directly, acts as both UI and orchestrator. We split this: backend becomes an API service (FastAPI), telegram becomes a thin UI client.

## Architecture

```
Request(input, environment_id, user_id)
    │
    ▼
  Brain
    ├── Authorizer (solid) → resolves env/user, returns available routes
    ├── Router (dynamic, BaseGenAI) → picks controller from available routes
    └── Controller.execute(input, env, user) (BaseController)
            ├── preparer.prepare(input) → structured data
            └── use_case.execute(prepared, env, user) → response
```

Slash commands: Authorizer → direct controller dispatch (skip router).
NL input: Authorizer → Router → controller dispatch.
Background tasks: go through brain with system user + scheduler environment.

## Key Abstractions

### 1. BaseGenAI (template method for all LLM operations)

All dynamic logic in the system implements this. Router, dynamic preparers, dynamic use-cases — anything that calls an LLM.

```python
# backend/brain/base_genai.py

class BaseGenAI:
    MAX_DEPTH = 5

    def run(self, input, context, *, _depth=0) -> dict:
        if _depth >= self.MAX_DEPTH: raise RecursionLimitError
        template = self._pick_template(input, context)
        built_context = self._build_context(input, context)
        prompt = render(template, built_context)
        raw = self._call_ai(prompt)
        return self._parse_response(raw)

    # Children implement:
    def _pick_template(self, input, context) -> str: ...
    def _build_context(self, input, context) -> dict: ...
    def _call_ai(self, prompt) -> str: ...
    def _parse_response(self, raw) -> dict: ...
```

`_build_context` can itself delegate to another BaseGenAI (natural recursion).

### 2. BaseController (template method for all controllers)

Each controller has an associated preparer and use-case. They are separate objects.

```python
# backend/brain/base_controller.py

class BaseController:
    preparer: BasePreparer
    use_case: BaseUseCase

    def execute(self, input, env, user) -> Any:
        prepared = self.preparer.prepare(input, env, user)
        return self.use_case.execute(prepared, env, user)

class BasePreparer:
    def prepare(self, input, env, user) -> Any: ...
    # Solid: implement directly. Dynamic: extend BaseGenAI too.
```

### 3. Authorizer (solid, singleton)

```python
# backend/brain/authorizer.py

class Authorizer:
    def authorize(self, environment_id, user_id) -> AuthContext:
        env = resolve environment (from DB or default)
        user = resolve user/entity (from DB or default)
        routes = filter ROUTE_REGISTRY by env/user permissions
        return AuthContext(env, user, routes)
```

### 4. Router (dynamic, singleton, extends BaseGenAI)

```python
# backend/brain/router.py

class Router(BaseGenAI):
    # _pick_template → classify-command.md
    # _build_context → format available routes with descriptions/examples
    # _call_ai → gemini.call()
    # _parse_response → extract chosen route name
```

### 5. Brain (orchestrator)

```python
# backend/brain/__init__.py

class Brain:
    def process(self, input, environment_id, user_id) -> Any:
        auth = self.authorizer.authorize(environment_id, user_id)
        route = self.router.route(input, auth.routes)
        controller = route.controller
        return controller.execute(input, auth.env, auth.user)

    def process_command(self, command, args, environment_id, user_id) -> Any:
        auth = self.authorizer.authorize(environment_id, user_id)
        controller = ROUTES[command].controller
        return controller.execute(args, auth.env, auth.user)
```

## Route Registry

```python
# backend/brain/routes.py

@dataclass
class Route:
    name: str
    controller: BaseController
    description: str           # for router LLM prompt
    examples: list[str]        # for router LLM prompt
    permissions: set[str]      # checked by authorizer

ROUTES: dict[str, Route] = { ... }
```

## File Structure

`domain/` is removed entirely. Code is organized by command. Each command is self-contained: controller + preparer + solid logic. Brain holds base abstractions + all dynamic (LLM) use-cases. Memory/knowledge services move to infrastructure (they're data access used across many commands).

```
backend/
  brain/
    __init__.py              # Brain class
    authorizer.py            # Authorizer
    router.py                # Router (BaseGenAI)
    base_controller.py       # BaseController + BasePreparer
    base_genai.py            # BaseGenAI template
    routes.py                # Route registry + Route dataclass
    dynamic/                 # All BaseGenAI implementations
      __init__.py
      conversation_reply.py  # generate NL reply
      tech_support.py        # draft support answers
      query_db.py            # NL → SQL
      tool_routing.py        # decide which tools to use
      classify_teaching.py   # classify knowledge tier/domain
      inbox_classify.py      # classify incoming email
      support_draft.py       # draft support email reply
      editorial_assess.py    # assess editorial email
      summarize_article.py   # summarize article for ingestion
      extract_knowledge.py   # extract facts from conversations
      scrape_competitors.py  # summarize competitor content
      contractor_parse.py    # parse free-form contractor data

  commands/                  # One file (or directory) per command
    __init__.py
    conversation.py          # controller + pass-through preparer
    support.py               # controller + preparer (extract question, flags)
    code.py                  # controller + preparer (prompt, mode, session)
    health.py                # controller + solid health check logic
    teach.py                 # controller + pass-through preparer
    search.py                # controller + solid knowledge search logic
    query.py                 # controller + pass-through preparer
    ingest.py                # controller + solid article fetch orchestration
    knowledge_extract.py     # controller + solid pipeline orchestration
    inbox.py                 # controller + solid approval workflow state
    invoice/
      __init__.py            # controller + preparer (parse contractor+month)
      generate.py            # solid: single invoice generation
      batch.py               # solid: batch invoice generation
      prepare.py             # solid: load existing + export PDF
      resolve_amount.py      # solid: amount lookup from budget
    budget/
      __init__.py            # controller + preparer (parse month)
      compute.py             # solid: generate budget sheet
      redirect.py            # solid: budget redirect operations
    contractor/
      __init__.py            # controller + preparer
      validate.py            # solid: field validation (regex)
      create.py              # solid: create + save contractor
      sync_entities.py       # solid: sync to entity system
    bank/
      __init__.py            # controller + preparer
      parse_statement.py     # solid: CSV parsing + categorization

  infrastructure/
    gateways/                # UNCHANGED
      gemini_gateway.py
      republic_gateway.py
      query_gateway.py
      embedding_gateway.py
      email_gateway.py
      docs_gateway.py
      drive_gateway.py
      sheets_gateway.py
      airtable_gateway.py
      exchange_rate_gateway.py
      redefine_gateway.py
    repositories/            # UNCHANGED
      postgres/
      sheets/
    memory/                  # Shared memory subsystem (pure data access, no LLM)
      __init__.py
      memory_service.py      # remember, recall, entity CRUD
      retriever.py           # KnowledgeRetriever (vector search, formatting)
      admin.py               # AdminService (heuristic reply classification)
      user_lookup.py         # SupportUserLookup (user data fetching)

  wiring.py                  # Updated to wire brain + commands
  api.py                     # FastAPI app exposing Brain

common/                      # UNCHANGED
  models.py
  config.py
  prompt_loader.py
  google_auth.py
  email_utils.py

templates/                   # UNCHANGED (referenced by brain/dynamic/ implementations)
```

### What lives where

**`brain/`** — base abstractions + all LLM orchestration:
- `base_genai.py`, `base_controller.py` — template methods
- `authorizer.py`, `router.py` — global pipeline components
- `dynamic/` — every BaseGenAI implementation (anything that calls an LLM)

**`commands/`** — one file per command, self-contained:
- Controller (extends BaseController)
- Preparer (extends BasePreparer, or pass-through)
- Solid logic that belongs to this command (no LLM calls)
- Complex commands get a directory (invoice/, budget/, contractor/, bank/)

**`infrastructure/`** — external integrations + shared data access:
- Gateways (APIs, email, docs, sheets)
- Repositories (postgres, sheets)
- Memory subsystem (knowledge retriever, memory service, user lookup)

### What's removed

- `domain/` — entire directory gone
- `compose_request.py` — distributed into `brain/dynamic/` implementations
- `command_classifier.py` — absorbed into `brain/router.py`
- `conversation_service.py` → `brain/dynamic/conversation_reply.py`
- `tool_router.py` → `brain/dynamic/tool_routing.py`
- `query_tool.py` → `brain/dynamic/query_db.py`
- `tech_support_handler.py` → `brain/dynamic/tech_support.py` + `support_draft.py`
- `inbox_service.py` — LLM parts → `brain/dynamic/`, workflow state → `commands/inbox.py`
- `contractor_service.py` — LLM parsing → `brain/dynamic/`, create/validate → `commands/contractor/`
- `memory_service.py` → `infrastructure/memory/memory_service.py` (minus classify_teaching → brain/dynamic/)
- `knowledge_retriever.py` → `infrastructure/memory/retriever.py`

## Backend API

```python
# backend/api.py — FastAPI

POST /brain/process    {input, environment_id, user_id}  → NL processing
POST /brain/command    {command, args, environment_id, user_id}  → direct command
```

Telegram bot calls these instead of importing backend.
Backend runs as its own process (uvicorn).

## Telegram Bot Changes

Becomes a thin client:
- Receives telegram message → extracts (input, chat_id, user_id)
- Slash commands → `POST /brain/command`
- NL input → `POST /brain/process`
- Renders response (text, files, buttons)
- Manages FSM state for multi-step flows (deferred)
- Manages telegram-specific state (reply maps, callback data)

## Concrete Controllers

| Command | Preparer | Use-Case | Prep Type | UC Type |
|---|---|---|---|---|
| conversation | PassThrough | ConversationReply | solid | dynamic |
| support | SupportPreparer | TechSupport | solid | dynamic |
| code | CodePreparer | RunClaudeCode | solid | dynamic |
| health | PassThrough | CheckHealth | solid | solid |
| invoice | InvoicePreparer | GenerateInvoice | solid | solid |
| budget | BudgetPreparer | ComputeBudget | solid | solid |
| teach | PassThrough | ClassifyTeaching | solid | dynamic |
| ingest | PassThrough | IngestArticles | solid | dynamic |
| search | PassThrough | KnowledgeSearch | solid | solid |
| query | PassThrough | QueryDb | solid | dynamic |
| inbox | PassThrough | InboxClassify | solid | dynamic |

## Migration Strategy

### Phase 1: Base abstractions
- Create `backend/brain/` with `base_genai.py`, `base_controller.py`, `routes.py`
- Implement `authorizer.py`, `router.py`, `brain/__init__.py`
- Create `brain/dynamic/` directory

### Phase 2: Infrastructure memory + commands
- Move `knowledge_retriever` + `memory_service` + helpers → `infrastructure/memory/`
- Create `backend/commands/` directory
- Move solid use-case logic into command files/directories
- Create dynamic use-cases in `brain/dynamic/` by extracting LLM orchestration

### Phase 3: Wire controllers
- Implement controllers in each command file (wiring preparer + use-case)
- Wire route registry
- Brain.process() and Brain.process_command() work end-to-end

### Phase 4: API layer + telegram refactor
- Add FastAPI app exposing Brain
- Refactor telegram bot to call API endpoints
- Backend runs as separate process

### Phase 5: Cleanup
- Delete `domain/` directory
- Remove old wiring, handler_utils singletons
- Update tests

## Verification
- After Phase 1: base classes importable, no runtime errors
- After Phase 3: Brain.process() works for conversation, health, teach
- After Phase 4: telegram bot → API → brain → response, full flow
- Existing tests adapted throughout
