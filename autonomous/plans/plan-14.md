# Plan 14: Autonomous Multi-Stage Agentic Workflows

> Give the agent real execution power: tool-powered agent tasks, task dependency chains, web scraping, human checkpoints, and combined goal+plan creation. Goals become pipelines.

## Architecture Overview

Five interconnected features building on the existing Goals system. Phase 1 adds `depends_on` FK to tasks, enabling linear chains where each task's output feeds the next. Phase 2 creates `AgentTaskExecutor` that reuses the existing `conversation_handler` (ReAct loop) to give agent tasks access to tools (`web_search`, `web_scrape`, `search`, `republic_db`, `agent_db`). Phase 3 adds a `web_scrape` tool for content extraction from URLs. Phase 4 implements the checkpoint flow: when a pipeline reaches a user-assigned task, GoalMonitor creates a `checkpoint_ready` notification; the bot renders it with approve/edit/skip buttons; user action via `/interact` marks the task done and unblocks the chain. Phase 5 adds the `launch` action to the goals tool (combined create+plan). Updated templates and tests throughout.

Key design decisions:
- Tasks describe INTENT, not implementation. "Find 15 indie media outlets" not "use web_search then web_scrape"
- `depends_on` is a simple UUID FK, not a DAG — linear chains per goal
- `AgentTaskExecutor` reuses `conversation_handler` by composition, no ReAct refactoring
- Checkpoint = a user-assigned task in the chain that pauses execution
- No new "workflow" or "pipeline" entity — Goals ARE pipelines
- Notifications are the bridge between agent work and human decisions

---

## Phase 1 — Task Dependencies

### 1.1 Migration 012: add `depends_on` column

**File:** `src/backend/infrastructure/repositories/postgres/migrations/012_task_dependencies.sql`

```sql
-- 012: Task dependency chain — each task can depend on one predecessor.

ALTER TABLE tasks ADD COLUMN IF NOT EXISTS depends_on UUID REFERENCES tasks(id);

CREATE INDEX IF NOT EXISTS idx_tasks_depends_on ON tasks(depends_on)
    WHERE depends_on IS NOT NULL;
```

**Done when:**
- [ ] Migration applies cleanly on DB with existing goals/tasks
- [ ] `depends_on` column exists, nullable, FK to tasks(id)
- [ ] Index created

---

### 1.2 Update `GoalRepo` to support `depends_on`

**File:** `src/backend/infrastructure/repositories/postgres/goal_repo.py`

Change `create_task` signature and SQL:

```python
def create_task(  # noqa: PLR0913
    self, title: str, description: str | None = None, goal_id: str | None = None,
    trigger_condition: str | None = None, due_date=None, assigned_to: str = "user",
    depends_on: str | None = None,
) -> dict:
    with self._cursor() as cur:
        cur.execute(
            """INSERT INTO tasks (title, description, goal_id, trigger_condition, due_date, assigned_to, depends_on)
               VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *""",
            (title, description, goal_id, trigger_condition, due_date, assigned_to, depends_on),
        )
        return _row_to_dict(cur, cur.fetchone())
```

Add `"depends_on"` to the `valid` set in `update_task`:

```python
valid = {"title", "description", "status", "goal_id", "trigger_condition", "due_date", "assigned_to", "result", "depends_on"}
```

Add `get_task` method:

```python
def get_task(self, task_id: str) -> dict | None:
    with self._cursor() as cur:
        cur.execute("SELECT * FROM tasks WHERE id = %s", (task_id,))
        return _row_to_dict(cur, cur.fetchone())
```

**Done when:**
- [ ] `create_task(..., depends_on=some_task_id)` stores the FK
- [ ] `update_task(task_id, depends_on=...)` works
- [ ] `get_task(task_id)` returns a single task dict or None

---

### 1.3 Update `FakeDb` in conftest to support `depends_on`

**File:** `tests/conftest.py`

Update `create_task` to accept and store `depends_on`:

```python
def create_task(self, title: str, description: str | None = None, goal_id: str | None = None,  # noqa: PLR0913
                trigger_condition: str | None = None, due_date=None, assigned_to: str = "user",
                depends_on: str | None = None) -> dict:
    now = datetime.now(UTC)
    task = {
        "id": str(uuid.uuid4()), "title": title, "description": description,
        "goal_id": goal_id, "trigger_condition": trigger_condition,
        "due_date": due_date, "assigned_to": assigned_to, "depends_on": depends_on,
        "status": "pending", "result": None, "completed_at": None,
        "created_at": now,
    }
    self.tasks[task["id"]] = task
    return task
```

Add `"depends_on"` to the `valid` set in `update_task`.

Add `get_task`:

```python
def get_task(self, task_id: str) -> dict | None:
    return self.tasks.get(task_id)
```

**Done when:**
- [ ] `FakeDb.create_task` accepts `depends_on` kwarg
- [ ] `FakeDb.get_task` returns task by ID
- [ ] Existing tests still pass

---

### 1.4 Update `decompose-goal.md` template for dependency chains

**File:** `src/backend/templates/goals/decompose-goal.md`

```markdown
Разбей цель на конкретные задачи, образующие цепочку (pipeline).

## Цель
Название: {{TITLE}}
Описание: {{DESCRIPTION}}
Приоритет: {{PRIORITY}}
Дедлайн: {{DEADLINE}}

## Существующие задачи
{{EXISTING_TASKS}}

## Правила
- Каждая задача должна быть конкретной и проверяемой
- assigned_to: "user" для задач, требующих человека (встречи, финальные решения, утверждения, отправка писем); "agent" для того, что может сделать AI (анализ, черновики, поиск, мониторинг)
- depends_on_index: индекс задачи в массиве (0-based), от которой зависит данная задача, или null для первой задачи в цепочке
- Задачи образуют линейную цепочку: каждая следующая использует результат предыдущей
- Если пользователь должен утвердить промежуточный результат — создай задачу с assigned_to: "user" в нужном месте цепочки (checkpoint)
- Задачи описывают НАМЕРЕНИЕ, а не реализацию. Пример: "Найти 15 инди-медиа на русском языке" вместо "Использовать web_search для поиска"
- Не дублируй существующие задачи
- 3-7 задач обычно достаточно

Верни JSON:
{"tasks": [{"title": "...", "description": "...", "assigned_to": "user|agent", "depends_on_index": null|0|1|...}]}
```

**Done when:**
- [ ] Template references `depends_on_index` instead of `trigger_condition`
- [ ] Guidance about checkpoints included
- [ ] Intent-first task descriptions emphasized

---

### 1.5 Update `_plan` action to wire `depends_on` IDs

**File:** `src/backend/brain/tools/goals.py`

Replace the `_plan` function:

```python
def _plan(db, gemini, args: dict) -> dict:
    goal_id = args.get("goal_id")
    if not goal_id:
        return {"error": "Нужен goal_id"}
    goal = db.get_goal(goal_id)
    if not goal:
        return {"error": "Цель не найдена"}
    existing_tasks = db.list_tasks(goal_id=goal_id)
    existing_text = "\n".join(
        f"- [{t['status']}] {t['title']}" for t in existing_tasks
    ) or "(нет)"
    prompt = load_template("goals/decompose-goal.md", {
        "TITLE": goal["title"],
        "DESCRIPTION": goal.get("description") or "(нет)",
        "PRIORITY": str(goal["priority"]),
        "DEADLINE": str(goal.get("deadline") or "нет"),
        "EXISTING_TASKS": existing_text,
    })
    result = gemini.call(prompt)
    created = []
    for t in result.get("tasks", []):
        dep_idx = t.get("depends_on_index")
        depends_on = created[dep_idx]["id"] if dep_idx is not None and dep_idx < len(created) else None
        task = db.create_task(
            title=t["title"],
            description=t.get("description"),
            goal_id=goal_id,
            assigned_to=t.get("assigned_to", "user"),
            depends_on=depends_on,
        )
        created.append(task)
    return {"tasks_created": created}
```

Key change: tasks no longer use `trigger_condition`. Instead, `depends_on_index` from the LLM output is resolved to actual task UUIDs as each task is created sequentially.

**Done when:**
- [ ] `_plan` creates tasks with `depends_on` pointing to the previous task in chain
- [ ] `trigger_condition` no longer set by `_plan` (existing trigger tasks unaffected)
- [ ] First task in chain has `depends_on=None`

---

## Phase 2 — AgentTaskExecutor

### 2.1 Create `AgentTaskExecutor`

**File:** `src/backend/brain/agent_executor.py`

```python
"""Agent task executor — runs agent tasks through the full ReAct loop with tools."""

from __future__ import annotations

import logging

from backend.brain.authorizer import AuthContext
from backend.brain.tool import TOOLS, ToolContext

logger = logging.getLogger(__name__)

# Tools available to autonomous agent tasks
_AGENT_TOOLS = {"web_search", "web_scrape", "search", "republic_db", "agent_db"}


class AgentTaskExecutor:
    """Execute agent tasks using the conversation handler (ReAct loop)."""

    def __init__(self, conversation_fn):
        self._conversation_fn = conversation_fn

    def execute(self, task: dict, goal_context: str, dependency_result: str = "") -> dict:
        """Run a task through the ReAct loop. Returns {result, completed}."""
        input_text = self._build_input(task, goal_context, dependency_result)
        auth = self._build_auth()
        try:
            result = self._conversation_fn(input_text, auth)
            reply = result.get("reply", "")
            return {"result": reply, "completed": True}
        except Exception as e:
            logger.exception("AgentTaskExecutor failed for task %s", task.get("id"))
            return {"result": str(e), "completed": False}

    def _build_input(self, task: dict, goal_context: str, dependency_result: str) -> str:
        parts = [
            f"## Задача\n{task['title']}",
        ]
        if task.get("description"):
            parts.append(task["description"])
        parts.append(f"\n## Контекст цели\n{goal_context}")
        if dependency_result:
            parts.append(f"\n## Результат предыдущей задачи\n{dependency_result}")
        parts.append(
            "\n## Инструкция\n"
            "Выполни задачу, используя доступные инструменты. "
            "Верни конкретный результат: данные, текст, список, анализ. "
            "Без общих фраз."
        )
        return "\n".join(parts)

    def _build_auth(self) -> AuthContext:
        tools = [t for name, t in TOOLS.items() if name in _AGENT_TOOLS and t.conversational]
        ctx = ToolContext(
            env={"name": "agent_task", "system_context": "Автономное выполнение задачи агентом."},
            user={"id": "agent", "role": "admin"},
        )
        return AuthContext(ctx=ctx, tools=tools, env_name="agent_task", role="admin")
```

**Done when:**
- [ ] `AgentTaskExecutor` composes `conversation_fn` (does not import or modify `react.py`)
- [ ] `_build_auth` creates synthetic AuthContext with admin role and filtered tool subset
- [ ] `_build_input` assembles task title + description + goal context + dependency result
- [ ] Returns `{result, completed}` dict

---

### 2.2 Update `GoalMonitor` to use `AgentTaskExecutor`

**File:** `src/backend/commands/goal_monitor.py`

Update `__init__` to accept executor:

```python
class GoalMonitor:
    def __init__(self, db: DbGateway, gemini: GeminiGateway,
                 agent_executor: AgentTaskExecutor | None = None):
        self._db = db
        self._gemini = gemini
        self._executor = agent_executor
```

Update `run` to include checkpoints:

```python
def run(self) -> dict:
    triggered = self._check_triggers()
    overdue = self._check_deadlines()
    agent_results = self._execute_agent_tasks()
    checkpoints = self._check_checkpoints()
    return {
        "triggered": len(triggered),
        "overdue": len(overdue),
        "agent_completed": len(agent_results),
        "checkpoints": len(checkpoints),
    }
```

Replace `_execute_agent_tasks`:

```python
def _execute_agent_tasks(self) -> list[dict]:
    if not self._executor:
        return []
    tasks = self._db.list_tasks(status="in_progress", assigned_to="agent")
    results = []
    for task in tasks:
        try:
            # Check dependency is met
            if task.get("depends_on"):
                dep = self._db.get_task(task["depends_on"])
                if not dep or dep["status"] != "done":
                    continue  # dependency not met, skip
                dep_result = dep.get("result") or ""
            else:
                dep_result = ""

            goal = self._db.get_goal(task["goal_id"]) if task.get("goal_id") else None
            goal_context = f"{goal['title']}\n{goal.get('description') or ''}" if goal else "(нет)"

            result = self._executor.execute(task, goal_context, dep_result)

            if result.get("completed"):
                self._db.update_task(task["id"], status="done", result=result.get("result", ""))
                if task.get("goal_id"):
                    self._db.add_progress(task["goal_id"], f"Задача выполнена: {task['title']}", source="agent")
                self._db.create_notification("task_completed", {
                    "task_id": str(task["id"]),
                    "task_title": task["title"],
                    "result": result.get("result", ""),
                })
            else:
                self._db.update_task(task["id"], result=result.get("result", ""))
            results.append(task)
        except Exception:
            logger.exception("Failed to execute agent task %s", task.get("id"))
    return results
```

Add `_check_checkpoints`:

```python
def _check_checkpoints(self) -> list[dict]:
    """When an agent task completes and next task is user-assigned, create checkpoint notification."""
    checkpoints = []
    done_agent_tasks = self._db.list_tasks(status="done", assigned_to="agent")
    for task in done_agent_tasks:
        try:
            goal_tasks = self._db.list_tasks(goal_id=task["goal_id"]) if task.get("goal_id") else []
            for next_task in goal_tasks:
                if (next_task.get("depends_on") == task["id"]
                        and next_task["assigned_to"] == "user"
                        and next_task["status"] == "pending"):
                    self._db.update_task(next_task["id"], status="in_progress")
                    self._db.create_notification("checkpoint_ready", {
                        "task_id": str(next_task["id"]),
                        "task_title": next_task["title"],
                        "task_description": next_task.get("description") or "",
                        "prev_task_title": task["title"],
                        "prev_result": task.get("result") or "",
                        "goal_id": str(task.get("goal_id", "")),
                    })
                    checkpoints.append(next_task)
        except Exception:
            logger.exception("Failed checkpoint check for task %s", task.get("id"))
    return checkpoints
```

The `_check_triggers` and `_check_deadlines` methods remain unchanged.

**Done when:**
- [ ] `GoalMonitor.__init__` accepts optional `agent_executor`
- [ ] `_execute_agent_tasks` uses `AgentTaskExecutor` instead of `gemini.call`
- [ ] Dependency result from predecessor task is passed to executor
- [ ] Tasks with unmet dependencies are skipped
- [ ] `_check_checkpoints` finds completed agent tasks and creates `checkpoint_ready` notifications for pending user tasks that depend on them

---

### 2.3 Wire `AgentTaskExecutor` into `GoalMonitor` in `run.py`

**File:** `src/backend/run.py`

Update the `_goal_monitor_loop` to create the executor:

```python
async def _goal_monitor_loop():
    retriever = KnowledgeRetriever(db=db, embed=EmbeddingGateway())
    conv_fn = conversation_handler(gemini, db, retriever)
    executor = AgentTaskExecutor(conv_fn)
    monitor = GoalMonitor(db, gemini, agent_executor=executor)
    while True:
        await asyncio.sleep(GOAL_MONITOR_INTERVAL)
        try:
            result = await asyncio.get_event_loop().run_in_executor(None, monitor.run)
            logger.info("GoalMonitor: %s", result)
        except Exception:
            logger.exception("GoalMonitor failed")
```

With necessary imports added at top:
```python
from backend.brain.agent_executor import AgentTaskExecutor
from backend.brain.react import conversation_handler
from backend.infrastructure.memory.retriever import KnowledgeRetriever
from backend.infrastructure.gateways.embedding_gateway import EmbeddingGateway
```

**Done when:**
- [ ] `GoalMonitor` receives an `AgentTaskExecutor` with a real `conversation_handler`
- [ ] Agent tasks now have access to tools during execution

---

## Phase 3 — Web Scrape Tool

### 3.1 Add `trafilatura` to requirements

**File:** `src/backend/requirements.txt`

Add line:
```
trafilatura>=2.0,<3
```

Note: `httpx` is already a dependency transitively. `trafilatura` is the new dependency for content extraction.

**Done when:**
- [ ] `trafilatura` in `requirements.txt`
- [ ] `pip install -r requirements.txt` succeeds

---

### 3.2 Create `web_scrape` tool

**File:** `src/backend/brain/tools/web_scrape.py`

```python
"""Web scrape tool — fetch URL and extract content."""

from __future__ import annotations

import logging

import httpx
import trafilatura

from backend.brain.tool import Tool, ToolContext

logger = logging.getLogger(__name__)

_MAX_TEXT_LENGTH = 5000
_TIMEOUT = 15


def make_web_scrape_tool() -> Tool:
    def fn(args: dict, _ctx: ToolContext) -> dict:
        url = args.get("url", "")
        if not url:
            return {"error": "Нужен url"}
        try:
            resp = httpx.get(url, timeout=_TIMEOUT, follow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0 (compatible; RepublicBot/1.0)"})
            resp.raise_for_status()
        except httpx.HTTPError as e:
            return {"error": f"Не удалось загрузить: {e}"}
        extracted = trafilatura.extract(resp.text, include_links=True, include_tables=True)
        if not extracted:
            return {"error": "Не удалось извлечь текст", "url": url}
        metadata = trafilatura.extract_metadata(resp.text)
        title_text = metadata.title if metadata and metadata.title else url
        text = extracted[:_MAX_TEXT_LENGTH]
        if len(extracted) > _MAX_TEXT_LENGTH:
            text += f"\n\n[обрезано, полный текст {len(extracted)} символов]"
        return {"title": title_text, "text": text, "url": url}

    return Tool(
        name="web_scrape",
        description="Загрузить веб-страницу и извлечь текст. Используй после web_search для получения полного содержания.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL страницы для загрузки"},
            },
            "required": ["url"],
        },
        fn=fn,
        permissions={},
        nl_routable=False,
        conversational=True,
    )
```

**Done when:**
- [ ] `web_scrape` fetches a URL via httpx
- [ ] `trafilatura` extracts clean text content
- [ ] Text truncated to 5000 chars with truncation notice
- [ ] Returns `{title, text, url}` or `{error}`
- [ ] Tool is conversational (available in ReAct loop)

---

### 3.3 Register `web_scrape` tool

**File:** `src/backend/brain/tools/__init__.py`

Add import and export:
```python
from backend.brain.tools.web_scrape import make_web_scrape_tool
```

Add to `__all__`: `"make_web_scrape_tool",`

**File:** `src/backend/wiring.py`

Add to import from `backend.brain.tools`:
```python
make_web_scrape_tool,
```

In `_register_core_tools`, add after `make_web_search_tool`:
```python
register_tool(make_web_scrape_tool())
```

**Done when:**
- [ ] `web_scrape` appears in `TOOLS` dict at startup
- [ ] Listed in `_AGENT_TOOLS` in `agent_executor.py`

---

### 3.4 Migration 013: `web_scrape` tool permissions

**File:** `src/backend/infrastructure/repositories/postgres/migrations/013_web_scrape_permission.sql`

```sql
-- 013: web_scrape tool permission — admin only by default.

INSERT INTO tool_permissions (tool_name, environment, allowed_roles) VALUES
    ('web_scrape', '*', ARRAY['admin'])
ON CONFLICT DO NOTHING;
```

**Done when:**
- [ ] `web_scrape` permission granted to admin in all environments

---

## Phase 4 — Checkpoint Flow

### 4.1 Add `checkpoint_action` interact handler

**File:** `src/backend/interact/admin.py`

Add method to `AdminHandlers`:

```python
def checkpoint_action(self, payload: Payload, ctx: InteractContext) -> dict:
    """Handle user response to a checkpoint notification."""
    task_id = payload.get("task_id", "")
    action = payload.get("action", "")  # approve, skip
    edit_text = payload.get("edit_text", "")

    if not task_id:
        return respond([msg("Не указан task_id.")])

    task = self._db.get_task(task_id)
    if not task:
        return respond([msg("Задача не найдена.")])

    if action == "approve":
        result = edit_text or "Утверждено пользователем"
        self._db.update_task(task_id, status="done", result=result)
        if task.get("goal_id"):
            self._db.add_progress(task["goal_id"], f"Checkpoint пройден: {task['title']}", source="user")
        _activate_next_task(self._db, task)
        return respond([msg(f"Checkpoint пройден: {task['title']}")])

    if action == "skip":
        self._db.update_task(task_id, status="done", result="Пропущено пользователем")
        _activate_next_task(self._db, task)
        return respond([msg(f"Checkpoint пропущен: {task['title']}")])

    return respond([msg(f"Неизвестное действие: {action}")])
```

Add module-level helper:

```python
def _activate_next_task(db, completed_task: dict) -> None:
    """Find and activate the next task in chain after a checkpoint."""
    if not completed_task.get("goal_id"):
        return
    goal_tasks = db.list_tasks(goal_id=completed_task["goal_id"])
    for task in goal_tasks:
        if task.get("depends_on") == completed_task["id"] and task["status"] == "pending":
            db.update_task(task["id"], status="in_progress")
            break
```

**File:** `src/backend/interact/__init__.py`

Add to `_HANDLERS`:
```python
"checkpoint_action": _admin.checkpoint_action,
```

**Done when:**
- [ ] `checkpoint_action` with `action=approve` marks task done and activates next
- [ ] `checkpoint_action` with `action=skip` marks task done (skipped) and activates next
- [ ] Next agent task in chain gets `status=in_progress`, ready for GoalMonitor pickup

---

### 4.2 Bot notification rendering for `checkpoint_ready`

**File:** `src/client/telegram_bot/handlers/goal_notifications.py`

Add checkpoint formatting:

```python
def _format_checkpoint(payload: dict) -> tuple[str, list[list[dict]]]:
    """Format checkpoint notification with action buttons."""
    text = (
        f"Checkpoint: {payload.get('task_title', '?')}\n\n"
        f"Предыдущая задача: {payload.get('prev_task_title', '?')}\n"
        f"Результат:\n{payload.get('prev_result', '(нет)')}\n\n"
        f"Что дальше: {payload.get('task_description') or payload.get('task_title', '?')}"
    )
    task_id = payload.get("task_id", "")
    keyboard = [
        [{"text": "Утвердить", "callback_data": f"chk:approve:{task_id}"}],
        [{"text": "Пропустить", "callback_data": f"chk:skip:{task_id}"}],
    ]
    return text, keyboard
```

Update notification sending to handle checkpoints with inline keyboard:

```python
if n.get("type") == "checkpoint_ready":
    text, keyboard = _format_checkpoint(n.get("payload", {}))
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=btn["text"], callback_data=btn["callback_data"])
         for btn in row]
        for row in keyboard
    ])
    await bot.send_message(admin_id, text, reply_markup=markup)
else:
    text = _format_notification(n)
    await bot.send_message(admin_id, text)
```

**Done when:**
- [ ] `checkpoint_ready` notifications render with buttons (approve/skip)
- [ ] Other notification types still render as plain text
- [ ] Buttons include task_id in callback data

---

### 4.3 Bot callback handler for checkpoint buttons

**File:** `src/client/telegram_bot/handlers/goal_notifications.py`

Add callback handler:

```python
async def checkpoint_callback(callback: types.CallbackQuery) -> None:
    """Handle checkpoint approve/skip buttons."""
    data = callback.data or ""
    if not data.startswith("chk:"):
        return
    parts = data.split(":", 2)
    if len(parts) < 3:
        await callback.answer("Неверные данные")
        return
    action, task_id = parts[1], parts[2]
    result = await backend_client.interact(
        "checkpoint_action",
        payload={"task_id": task_id, "action": action},
    )
    messages = result.get("messages", [])
    text = messages[0]["text"] if messages else "Готово"
    await callback.message.answer(text)
    await callback.answer()
```

**File:** `src/client/telegram_bot/main.py`

Register the callback handler:

```python
from telegram_bot.handlers.goal_notifications import checkpoint_callback
dp.callback_query.register(checkpoint_callback, lambda c: c.data and c.data.startswith("chk:"))
```

**Done when:**
- [ ] Pressing "Утвердить" calls `/interact` with `checkpoint_action` + `action=approve`
- [ ] Pressing "Пропустить" calls `/interact` with `checkpoint_action` + `action=skip`
- [ ] Response message shown to user

---

## Phase 5 — `launch` Action on Goals Tool

### 5.1 Add `_launch` to goals tool

**File:** `src/backend/brain/tools/goals.py`

Add function:

```python
def _launch(db, gemini, args: dict) -> dict:
    """Create goal + decompose in one step."""
    created = _create(db, gemini, args)
    if "error" in created:
        return created
    goal_id = created["goal"]["id"]
    planned = _plan(db, gemini, {"goal_id": goal_id})
    if "error" in planned:
        return {"goal": created["goal"], "plan_error": planned["error"]}
    # Activate first task in chain
    tasks = planned.get("tasks_created", [])
    if tasks:
        first = tasks[0]
        if first["assigned_to"] == "agent":
            db.update_task(first["id"], status="in_progress")
    return {
        "goal": created["goal"],
        "tasks_created": tasks,
        "confirmation": f"Цель создана и декомпозирована на {len(tasks)} задач",
    }
```

Add to `_ACTIONS`:
```python
_ACTIONS = {
    "list": _list,
    "create": _create,
    "update": _update,
    "plan": _plan,
    "progress": _progress,
    "status": _status,
    "launch": _launch,
}
```

Update the Tool parameters `action` enum:
```python
"enum": ["list", "create", "update", "plan", "progress", "status", "launch"],
```

Update `action` description:
```python
"description": "list=все цели, create=новая цель, update=обновить цель/задачу, plan=декомпозировать на задачи, progress=записать прогресс, status=подробный статус, launch=создать цель и сразу декомпозировать",
```

**Done when:**
- [ ] `launch` creates a goal and decomposes it in one call
- [ ] First agent task in chain is activated (`status=in_progress`)
- [ ] Returns both goal and tasks_created

---

## Phase 6 — Tests

### 6.1 Test task dependencies

**File:** `tests/test_goals_tool.py`

```python
def test_plan_creates_dependency_chain(fake_db, fake_gemini):
    tool = make_goals_tool(fake_db, fake_gemini)
    created = tool.fn({"action": "create", "title": "Pipeline goal"}, _ctx())
    goal_id = created["goal"]["id"]

    fake_gemini.enqueue({"tasks": [
        {"title": "Research", "assigned_to": "agent", "depends_on_index": None},
        {"title": "Review", "assigned_to": "user", "depends_on_index": 0},
        {"title": "Execute", "assigned_to": "agent", "depends_on_index": 1},
    ]})

    result = tool.fn({"action": "plan", "goal_id": goal_id}, _ctx())
    tasks = result["tasks_created"]
    assert len(tasks) == 3
    assert tasks[0]["depends_on"] is None
    assert tasks[1]["depends_on"] == tasks[0]["id"]
    assert tasks[2]["depends_on"] == tasks[1]["id"]
```

**Done when:**
- [ ] `_plan` correctly wires `depends_on` from LLM's `depends_on_index`

---

### 6.2 Test `launch` action

**File:** `tests/test_goals_tool.py`

```python
def test_launch_creates_and_plans(fake_db, fake_gemini):
    tool = make_goals_tool(fake_db, fake_gemini)
    fake_gemini.enqueue({"tasks": [
        {"title": "T1", "assigned_to": "agent", "depends_on_index": None},
        {"title": "T2", "assigned_to": "user", "depends_on_index": 0},
    ]})
    result = tool.fn({"action": "launch", "title": "New initiative", "description": "Do things"}, _ctx())
    assert "goal" in result
    assert len(result["tasks_created"]) == 2
    # First agent task activated
    first_task = fake_db.get_task(result["tasks_created"][0]["id"])
    assert first_task["status"] == "in_progress"


def test_launch_missing_title(fake_db, fake_gemini):
    tool = make_goals_tool(fake_db, fake_gemini)
    result = tool.fn({"action": "launch"}, _ctx())
    assert "error" in result
```

**Done when:**
- [ ] `launch` combines create + plan
- [ ] First agent task auto-activated

---

### 6.3 Test `AgentTaskExecutor`

**File:** `tests/test_agent_executor.py`

```python
"""Tests for AgentTaskExecutor."""

from backend.brain.agent_executor import AgentTaskExecutor


def test_executor_builds_input_with_dependency():
    calls = []

    def mock_conv_fn(input_text, auth, **kwargs):
        calls.append(input_text)
        return {"reply": "Agent completed the research"}

    executor = AgentTaskExecutor(mock_conv_fn)
    task = {"id": "t1", "title": "Analyze results", "description": "Deep analysis"}
    result = executor.execute(task, "Goal: launch media", "Previous: found 10 outlets")

    assert result["completed"] is True
    assert "Agent completed the research" in result["result"]
    assert "Analyze results" in calls[0]
    assert "found 10 outlets" in calls[0]


def test_executor_handles_error():
    def failing_fn(input_text, auth, **kwargs):
        raise RuntimeError("LLM unavailable")

    executor = AgentTaskExecutor(failing_fn)
    task = {"id": "t1", "title": "Fail task"}
    result = executor.execute(task, "Goal context")

    assert result["completed"] is False
    assert "LLM unavailable" in result["result"]
```

**Done when:**
- [ ] Executor passes task + dependency result to conversation_fn
- [ ] Error handling returns `completed=False`

---

### 6.4 Test GoalMonitor checkpoint flow

**File:** `tests/test_goal_monitor.py`

```python
"""Tests for GoalMonitor checkpoint detection."""

from backend.commands.goal_monitor import GoalMonitor


def test_checkpoint_created_when_agent_done_and_next_is_user(fake_db, fake_gemini):
    goal = fake_db.create_goal(title="Pipeline")
    t1 = fake_db.create_task(title="Research", goal_id=goal["id"], assigned_to="agent")
    t2 = fake_db.create_task(title="Approve", goal_id=goal["id"], assigned_to="user", depends_on=t1["id"])

    # Mark t1 as done (simulating agent completion)
    fake_db.update_task(t1["id"], status="done", result="Found 10 outlets")

    monitor = GoalMonitor(fake_db, fake_gemini)
    result = monitor.run()

    assert result["checkpoints"] == 1
    # t2 should be in_progress now
    assert fake_db.get_task(t2["id"])["status"] == "in_progress"
    # Notification created
    pending = fake_db.get_pending_notifications()
    checkpoint_notifs = [n for n in pending if n["type"] == "checkpoint_ready"]
    assert len(checkpoint_notifs) == 1
    assert checkpoint_notifs[0]["payload"]["task_id"] == str(t2["id"])


def test_no_checkpoint_when_next_is_agent(fake_db, fake_gemini):
    goal = fake_db.create_goal(title="Pipeline")
    t1 = fake_db.create_task(title="Step 1", goal_id=goal["id"], assigned_to="agent")
    t2 = fake_db.create_task(title="Step 2", goal_id=goal["id"], assigned_to="agent", depends_on=t1["id"])
    fake_db.update_task(t1["id"], status="done", result="Done")

    monitor = GoalMonitor(fake_db, fake_gemini)
    result = monitor.run()

    assert result["checkpoints"] == 0
```

**Done when:**
- [ ] Checkpoint created when agent task done + next user task pending
- [ ] No checkpoint when next task is also agent-assigned

---

### 6.5 Test checkpoint_action interact handler

**File:** `tests/test_interact.py` (append)

```python
def test_checkpoint_approve_activates_next_task(fake_db):
    goal = fake_db.create_goal(title="Pipeline")
    t_user = fake_db.create_task(title="Review", goal_id=goal["id"], assigned_to="user")
    t_next = fake_db.create_task(title="Send", goal_id=goal["id"], assigned_to="agent", depends_on=t_user["id"])
    fake_db.update_task(t_user["id"], status="in_progress")

    # Simulate approve
    from backend.interact.admin import _activate_next_task
    fake_db.update_task(t_user["id"], status="done", result="Approved")
    _activate_next_task(fake_db, fake_db.get_task(t_user["id"]))

    assert fake_db.get_task(t_next["id"])["status"] == "in_progress"
```

**Done when:**
- [ ] Approve sets task status to done and activates next
- [ ] Skip sets task status to done (skipped) and activates next

---

## Phase 7 — Documentation & External TODOs

### 7.1 Update `docs/diagrams/brain-flows.md`

In the "Component Wiring" section, add `web_scrape`:
```
│  ├── web_scrape     (conv)           │
```

Update "6. Goal Monitor" section to reflect new flow:

```
## 6. Goal Monitor (Background)

Cron (every GOAL_MONITOR_INTERVAL) ──▶ GoalMonitor.run()
                                           │
                                           ├──▶ _check_triggers()
                                           │        (unchanged)
                                           │
                                           ├──▶ _check_deadlines()
                                           │        (unchanged)
                                           │
                                           ├──▶ _execute_agent_tasks()
                                           │        ├── DB: get in_progress agent tasks
                                           │        ├── Check depends_on task is done
                                           │        ├── AgentTaskExecutor: ReAct loop with tools
                                           │        │     ├── web_search, web_scrape, search
                                           │        │     └── republic_db, agent_db
                                           │        └── Mark done, notify
                                           │
                                           └──▶ _check_checkpoints()
                                                    ├── Find done agent tasks
                                                    ├── If next task is user-assigned + pending
                                                    └── Create checkpoint_ready notification
                                                           │
                                                           ▼
                                                    Bot renders with buttons
                                                    User: approve/skip
                                                    ──▶ /interact checkpoint_action
                                                    ──▶ Mark user task done
                                                    ──▶ Activate next agent task
```

Add new section:

```
## 7. Autonomous Pipeline (Goal → Tasks → Execute → Checkpoint → Continue)

User: "Research 15 indie media and draft outreach emails"
  ──▶ Brain (ReAct) ──▶ goals tool (launch action)
       │
       ├── create_goal("Research indie media for outreach")
       └── decompose into chained tasks:
             T1 [agent] Research indie media outlets (depends_on: null)
             T2 [agent] Draft outreach emails (depends_on: T1)
             T3 [user]  Review and approve emails (depends_on: T2) ← checkpoint
             T4 [agent] Compile final report (depends_on: T3)

GoalMonitor tick:
  T1 is in_progress + agent → AgentTaskExecutor runs with tools
  T1 done → T2 activated (agent, depends_on met)
  T2 done → T3 is user-assigned → checkpoint_ready notification
  User approves T3 → T4 activated
  T4 done → goal complete
```

**Done when:**
- [ ] `web_scrape` tool listed in component wiring
- [ ] Goal Monitor section updated with AgentTaskExecutor and checkpoints
- [ ] New Section 7 documents the full pipeline flow

---

### 7.2 Update `autonomous/dev/external-todo.md`

Append:

```markdown
## Autonomous Pipelines (Plan 14)

- [ ] Deploy migration 012 (task depends_on column)
- [ ] Deploy migration 013 (web_scrape permission)
- [ ] Add `trafilatura` to Docker image
- [ ] Test full pipeline: create goal via "launch" → agent tasks execute with tools → checkpoint notification → approve → next task
- [ ] Monitor GoalMonitor logs for agent task execution quality
- [ ] Tune agent task tool subset if needed (add/remove tools from _AGENT_TOOLS)
- [ ] Verify checkpoint notifications render correctly in Telegram with buttons
- [ ] Test checkpoint approve/skip callback flow end-to-end
```

**Done when:**
- [ ] External TODO section added with deployment steps

---

## Implementation Order

```
Phase 1 (1.1 → 1.2 → 1.3 → 1.4 → 1.5) — Task dependencies (foundation)
  ↓
Phase 2 (2.1 → 2.2 → 2.3) — AgentTaskExecutor (depends on Phase 1 for depends_on)
  ↓
Phase 3 (3.1 → 3.2 → 3.3 → 3.4) — Web scrape tool (independent, but needed by Phase 2 at runtime)
  ↓
Phase 4 (4.1 → 4.2 → 4.3) — Checkpoint flow (depends on Phase 2 for notifications)
  ↓
Phase 5 (5.1) — launch action (depends on Phase 1 for _plan with depends_on)
  ↓
Phase 6 (6.1 → 6.2 → 6.3 → 6.4 → 6.5) — Tests (after all features)
  ↓
Phase 7 (7.1 → 7.2) — Docs & external TODOs
```

Note: Phase 3 can be implemented in parallel with Phase 1-2, but agent tasks need `web_scrape` registered in TOOLS before they can use it at runtime.

## Files Created (new)

- `src/backend/infrastructure/repositories/postgres/migrations/012_task_dependencies.sql`
- `src/backend/infrastructure/repositories/postgres/migrations/013_web_scrape_permission.sql`
- `src/backend/brain/agent_executor.py`
- `src/backend/brain/tools/web_scrape.py`
- `tests/test_agent_executor.py`
- `tests/test_goal_monitor.py`

## Files Modified

- `src/backend/infrastructure/repositories/postgres/goal_repo.py` — `create_task` accepts `depends_on`, `get_task` method, `update_task` valid set
- `src/backend/brain/tools/goals.py` — `_plan` wires depends_on, `_launch` action, `_ACTIONS` dict, Tool parameters
- `src/backend/brain/tools/__init__.py` — export `make_web_scrape_tool`
- `src/backend/wiring.py` — register `web_scrape` tool
- `src/backend/commands/goal_monitor.py` — `AgentTaskExecutor` integration, `_check_checkpoints`, dependency checks
- `src/backend/run.py` — wire `AgentTaskExecutor` into GoalMonitor
- `src/backend/templates/goals/decompose-goal.md` — depends_on_index, checkpoint guidance
- `src/backend/requirements.txt` — `trafilatura`
- `src/backend/interact/__init__.py` — `checkpoint_action` handler
- `src/backend/interact/admin.py` — `checkpoint_action` method, `_activate_next_task` helper
- `src/client/telegram_bot/handlers/goal_notifications.py` — checkpoint rendering, callback handler
- `src/client/telegram_bot/main.py` — register checkpoint callback
- `tests/conftest.py` — `FakeDb.create_task` accepts `depends_on`, `get_task` method
- `tests/test_goals_tool.py` — plan dependency chain, launch tests
- `tests/test_interact.py` — checkpoint_action tests
- `docs/diagrams/brain-flows.md` — web_scrape, pipeline flow, updated Goal Monitor
- `autonomous/dev/external-todo.md` — Plan 14 deployment steps
