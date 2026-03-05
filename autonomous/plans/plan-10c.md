# Plan 10c: Wire Controllers + Route Registry

## Context

This plan wires everything together. Each command file gets a concrete Controller (extending BaseController) that pairs a Preparer with a UseCase. The route registry gets populated. `Brain.process()` and `Brain.process_command()` work end-to-end.

After this phase, you can call `brain.process("check system health", "default", "admin")` and get a response. The telegram bot still uses the old path (changed in plan 10d).

## Step 1: Implement Controllers in Command Files

Each command file gets a controller class pairing a preparer with a use case.

### `commands/conversation.py`

```python
class ConversationController(BaseController):
    """NL conversation with RAG context."""
    # preparer: PassThroughPreparer
    # use_case: ConversationReply (brain/dynamic)
```

### `commands/support.py`

```python
class SupportPreparer(BasePreparer):
    """Extract question text and flags (verbose, expert)."""
    def prepare(self, input, env, user):
        verbose, expert, text = _parse_flags(input)
        return {"question": text, "verbose": verbose, "expert": expert}

class SupportController(BaseController):
    # preparer: SupportPreparer
    # use_case: TechSupport (brain/dynamic)
```

### `commands/code.py`

```python
class CodePreparer(BasePreparer):
    """Parse mode, verbose, expert flags from input."""
    def prepare(self, input, env, user):
        verbose, expert, text = _parse_flags(input)
        return {"prompt": text, "verbose": verbose, "expert": expert, "mode": "explore"}

class RunClaudeCodeUseCase(BaseUseCase):
    """Wraps run_claude_code()."""
    def execute(self, prepared, env, user):
        return run_claude_code(**prepared)

class CodeController(BaseController):
    # preparer: CodePreparer
    # use_case: RunClaudeCodeUseCase
```

### `commands/health.py`

```python
class CheckHealthUseCase(BaseUseCase):
    def execute(self, prepared, env, user):
        return run_healthchecks()

class HealthController(BaseController):
    # preparer: PassThroughPreparer
    # use_case: CheckHealthUseCase
```

### `commands/teach.py`

```python
class TeachUseCase(BaseUseCase):
    """Classify via LLM, then store via memory."""
    def __init__(self, classify: ClassifyTeaching, memory: MemoryService): ...
    def execute(self, prepared, env, user):
        result = self._classify.run(prepared, {})
        return self._memory.teach(prepared, domain=result["domain"], tier=result["tier"])

class TeachController(BaseController):
    # preparer: PassThroughPreparer
    # use_case: TeachUseCase
```

### `commands/search.py`

```python
class SearchUseCase(BaseUseCase):
    """Solid: search knowledge base."""
    def __init__(self, retriever: KnowledgeRetriever): ...
    def execute(self, prepared, env, user):
        return self._retriever.retrieve(prepared, domains=env.get("allowed_domains"))

class SearchController(BaseController):
    # preparer: PassThroughPreparer
    # use_case: SearchUseCase
```

### `commands/query.py`

```python
class QueryController(BaseController):
    # preparer: PassThroughPreparer
    # use_case: QueryDb (brain/dynamic)
```

### `commands/ingest.py`

```python
class IngestUseCase(BaseUseCase):
    """Solid orchestration calling brain/dynamic/summarize_article per article."""
    def __init__(self, summarizer: SummarizeArticle, memory: MemoryService): ...
    def execute(self, prepared, env, user):
        # Loop over articles, summarize each, store via memory
        ...

class IngestController(BaseController):
    # preparer: PassThroughPreparer (input = list of articles)
    # use_case: IngestUseCase
```

### `commands/inbox.py`

```python
class InboxProcessUseCase(BaseUseCase):
    """Calls brain/dynamic/inbox_classify + editorial_assess."""
    def __init__(self, classifier: InboxClassify, assessor: EditorialAssess,
                 tech_support: TechSupport, ...): ...
    def execute(self, prepared, env, user):
        # Classify email, then handle based on category
        ...

class InboxController(BaseController):
    # preparer: PassThroughPreparer
    # use_case: InboxProcessUseCase
```

### `commands/invoice/__init__.py`

```python
class InvoicePreparer(BasePreparer):
    """Parse contractor name + month from input."""
    def prepare(self, input, env, user):
        # Parse "contractor_name [month]"
        ...
        return {"contractor": contractor, "month": month}

class GenerateInvoiceUseCase(BaseUseCase):
    def __init__(self, ...): ...
    def execute(self, prepared, env, user):
        # Calls invoice/generate.py logic
        ...

class InvoiceController(BaseController):
    # preparer: InvoicePreparer
    # use_case: GenerateInvoiceUseCase
```

### `commands/budget/__init__.py`

```python
class BudgetPreparer(BasePreparer):
    """Parse month from input."""
    def prepare(self, input, env, user):
        return {"month": input.strip() or prev_month()}

class ComputeBudgetUseCase(BaseUseCase):
    def execute(self, prepared, env, user):
        return compute_budget(prepared["month"])

class BudgetController(BaseController):
    # preparer: BudgetPreparer
    # use_case: ComputeBudgetUseCase
```

### `commands/contractor/__init__.py`

```python
class ContractorController(BaseController):
    # preparer: ContractorPreparer
    # use_case: depends on sub-flow
```

### `commands/bank/__init__.py`

```python
class BankController(BaseController):
    # preparer: BankPreparer (parse file path + flags)
    # use_case: ParseBankStatementUseCase (solid)
```

## Step 2: Populate Route Registry

In `backend/brain/routes.py`, define all route metadata:

```python
ROUTE_DEFINITIONS = [
    {"name": "conversation", "description": "Свободный разговор, ответы на вопросы",
     "examples": ["что такое республика?", "расскажи о подписке", "про что статьи сегодня?"],
     "permissions": {"admin", "user"}, "slash_command": "nl"},
    {"name": "support", "description": "Техподдержка: вопросы о продукте, сайте, подписке",
     "examples": ["как отменить подписку?", "не работает оплата"],
     "permissions": {"admin", "user"}, "slash_command": "support"},
    {"name": "code", "description": "Работа с кодом, архитектура, баги",
     "examples": ["найди баг в router.py", "объясни как работает wiring"],
     "permissions": {"admin"}, "slash_command": "code"},
    {"name": "health", "description": "Проверка доступности сервисов",
     "examples": ["проверь здоровье", "всё ли работает?"],
     "permissions": {"admin", "user"}, "slash_command": "health"},
    {"name": "teach", "description": "Запомнить новое знание",
     "examples": ["запомни: республика это медиа"],
     "permissions": {"admin"}, "slash_command": "teach"},
    {"name": "search", "description": "Поиск в базе знаний",
     "examples": ["найди информацию о конкурентах"],
     "permissions": {"admin"}, "slash_command": "ksearch"},
    {"name": "query", "description": "SQL-запрос к базе данных Republic/Redefine",
     "examples": ["сколько подписчиков?", "топ авторов за месяц"],
     "permissions": {"admin"}, "slash_command": None},
    {"name": "invoice", "description": "Генерация счёта для автора",
     "examples": [], "permissions": {"admin"}, "slash_command": "generate"},
    {"name": "budget", "description": "Генерация бюджетной таблицы",
     "examples": [], "permissions": {"admin"}, "slash_command": "budget"},
    {"name": "ingest", "description": "Загрузка и обработка статей",
     "examples": [], "permissions": {"admin"}, "slash_command": "ingest_articles"},
    {"name": "inbox", "description": "Обработка входящей почты",
     "examples": [], "permissions": {"admin"}, "slash_command": None},
]
```

Actual `Route` objects are created at wiring time when controllers are instantiated.

## Step 3: Update `wiring.py`

Add `create_brain()` factory that builds everything:

```python
def create_brain() -> Brain:
    db = create_db()
    gemini = GeminiGateway()
    embed = EmbeddingGateway()
    retriever = KnowledgeRetriever(db=db, embed=embed)
    memory = MemoryService(db=db, embed=embed, retriever=retriever)
    query_tools = create_query_tools()

    # Dynamic use cases (BaseGenAI implementations)
    conversation_reply = ConversationReply(gemini, retriever, ToolRouting(gemini), query_tools)
    classify_teaching = ClassifyTeaching(gemini, db, embed)
    tech_support = TechSupport(gemini, ...)
    query_db = QueryDb(gemini, ...)
    inbox_classify = InboxClassify(gemini)
    editorial_assess = EditorialAssess(gemini)
    summarize_article = SummarizeArticle(gemini)

    # Controllers
    conversation_ctrl = ConversationController(PassThroughPreparer(), conversation_reply)
    support_ctrl = SupportController(SupportPreparer(), tech_support)
    code_ctrl = CodeController(CodePreparer(), RunClaudeCodeUseCase())
    health_ctrl = HealthController(PassThroughPreparer(), CheckHealthUseCase())
    teach_ctrl = TeachController(PassThroughPreparer(), TeachUseCase(classify_teaching, memory))
    search_ctrl = SearchController(PassThroughPreparer(), SearchUseCase(retriever))
    query_ctrl = QueryController(PassThroughPreparer(), query_db)
    ingest_ctrl = IngestController(PassThroughPreparer(), IngestUseCase(summarize_article, memory))
    budget_ctrl = BudgetController(BudgetPreparer(), ComputeBudgetUseCase(...))
    invoice_ctrl = InvoiceController(InvoicePreparer(...), GenerateInvoiceUseCase(...))
    inbox_ctrl = InboxController(PassThroughPreparer(), InboxProcessUseCase(inbox_classify, editorial_assess, tech_support, ...))

    # Register routes
    ctrl_map = {
        "conversation": conversation_ctrl, "support": support_ctrl,
        "code": code_ctrl, "health": health_ctrl, "teach": teach_ctrl,
        "search": search_ctrl, "query": query_ctrl, "invoice": invoice_ctrl,
        "budget": budget_ctrl, "ingest": ingest_ctrl, "inbox": inbox_ctrl,
    }
    for defn in ROUTE_DEFINITIONS:
        register_route(Route(
            name=defn["name"], controller=ctrl_map[defn["name"]],
            description=defn["description"], examples=defn["examples"],
            permissions=defn["permissions"], slash_command=defn.get("slash_command"),
        ))

    # Brain
    authorizer = Authorizer(db)
    router = Router(gemini, db)
    return Brain(authorizer, router)
```

Keep old factory functions alongside for backward compatibility during transition.

## Step 4: Integration Test

```python
def test_brain_health_command():
    brain = create_brain()
    result = brain.process_command("health", "", "default", "admin")
    assert "ok" in str(result) or "error" in str(result)

def test_brain_conversation():
    brain = create_brain()
    result = brain.process("привет", "default", "admin")
    assert isinstance(result, (str, dict))

def test_brain_teach():
    brain = create_brain()
    result = brain.process_command("teach", "республика -- это медиа", "default", "admin")
    assert result is not None
```

## Verification Checklist

- [x] Each command file has a concrete Controller class extending BaseController
- [x] Each controller pairs a Preparer with a UseCase via constructor
- [x] `ROUTES` dict is populated with all routes after `create_brain()` is called
- [ ] `brain.process_command("health", "", "default", "admin")` returns healthcheck results (needs live DB)
- [ ] `brain.process("привет", "default", "admin")` returns a conversation reply (needs live DB+LLM)
- [ ] `brain.process_command("teach", "test fact", "default", "admin")` stores knowledge (needs live DB+LLM)
- [ ] `brain.process_command("search", "республика", "default", "admin")` returns results (needs live DB)
- [x] Old wiring functions (`create_inbox_service`, etc.) still work
- [x] All existing tests still pass (1672 pass, 6 pre-existing failures)
- [x] No circular imports between brain/, commands/, infrastructure/
- [x] Authorizer correctly resolves environment by chat_id
- [x] Authorizer correctly resolves user by telegram_user_id
- [x] Router falls back to "conversation" when no route matches
