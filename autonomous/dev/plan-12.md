# Plan 12: Goals & Tasks System

> Turn the agent from a reactive assistant into an autonomous copilot-publisher with goals, tasks, trigger-based activation, and proactive monitoring.

## Architecture Overview

Two new tables (`goals`, `tasks`) + auxiliary (`goal_progress`, `notifications`). Goals are strategic and flat (no hierarchy). Tasks are concrete sub-items of goals (or standalone). Tasks can have **trigger conditions** — free-text conditions evaluated by LLM periodically (pub/sub pattern). A background **GoalMonitor** cron checks triggers, deadlines, and executes agent-assigned tasks. Active goals are injected into the conversation system prompt so the agent is always goal-aware. Notifications flow to the bot via a polling endpoint (same pattern as email_listener).

---

## Phase 1 — Data Layer

### 1.1 Create migration `007_goals_and_tasks.sql`

**File:** `src/backend/infrastructure/repositories/postgres/migrations/007_goals_and_tasks.sql`

```sql
-- 007: Goals, tasks, progress, and notifications.

CREATE TABLE IF NOT EXISTS goals (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title       TEXT NOT NULL,
    description TEXT,
    status      TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'paused', 'done', 'abandoned')),
    priority    INT NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
    deadline    TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tasks (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    goal_id           UUID REFERENCES goals(id) ON DELETE SET NULL,
    title             TEXT NOT NULL,
    description       TEXT,
    status            TEXT NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'in_progress', 'done', 'blocked')),
    trigger_condition TEXT,
    due_date          TIMESTAMPTZ,
    assigned_to       TEXT NOT NULL DEFAULT 'user'
                      CHECK (assigned_to IN ('user', 'agent')),
    result            TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at      TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS goal_progress (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    goal_id    UUID NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    note       TEXT NOT NULL,
    source     TEXT NOT NULL DEFAULT 'user'
               CHECK (source IN ('user', 'agent', 'auto')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS notifications (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type       TEXT NOT NULL,
    payload    JSONB NOT NULL DEFAULT '{}',
    read       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_goals_status ON goals(status);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_goal_id ON tasks(goal_id);
CREATE INDEX IF NOT EXISTS idx_tasks_trigger ON tasks(trigger_condition)
    WHERE trigger_condition IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_notifications_unread ON notifications(read)
    WHERE read = FALSE;

-- Tool permissions: admin only, in relevant environments.
INSERT INTO tool_permissions (tool_name, environment, allowed_roles) VALUES
    ('goals', '*',               ARRAY['admin']),
    ('goals', 'admin_dm',        ARRAY['admin']),
    ('goals', 'editorial_group', ARRAY['admin']),
    ('goals', 'ceo_group',       ARRAY['admin'])
ON CONFLICT DO NOTHING;
```

**Done when:** File exists at the path above. Will auto-apply on next `init_schema()`.

---

### 1.2 Create `goal_repo.py`

**File:** `src/backend/infrastructure/repositories/postgres/goal_repo.py`

**Pattern to follow:** `permission_repo.py` — same `BasePostgresRepo` mixin, `self._cursor()`, `with cur:` context manager, manual dict construction from `cur.fetchall()`.

**Class:** `GoalRepo(BasePostgresRepo)`

**Helper (private, top of file):**

```python
def _row_to_dict(cur, row):
    """Convert a DB row to dict using cursor.description column names."""
    if row is None:
        return None
    return {col.name: val for col, val in zip(cur.description, row)}

def _rows_to_dicts(cur):
    return [_row_to_dict(cur, row) for row in cur.fetchall()]
```

**Methods (exact signatures and SQL):**

#### `create_goal(self, title: str, description: str = None, priority: int = 3, deadline: str = None) -> dict`
```sql
INSERT INTO goals (title, description, priority, deadline)
VALUES (%s, %s, %s, %s)
RETURNING *
```
Return `_row_to_dict(cur, cur.fetchone())`.

#### `update_goal(self, goal_id: str, **fields) -> dict`
Valid fields: `title`, `description`, `status`, `priority`, `deadline`. Raise `ValueError` for unknown fields.
Build SET clause dynamically: `SET field1=%s, field2=%s, ..., updated_at=NOW()`.
```sql
UPDATE goals SET {set_clause} WHERE id = %s RETURNING *
```
Return the updated dict.

#### `list_goals(self, status: str = None) -> list[dict]`
```sql
SELECT * FROM goals [WHERE status = %s] ORDER BY priority ASC, created_at DESC
```

#### `get_goal(self, goal_id: str) -> dict | None`
```sql
SELECT * FROM goals WHERE id = %s
```

#### `create_task(self, title: str, description: str = None, goal_id: str = None, trigger_condition: str = None, due_date: str = None, assigned_to: str = 'user') -> dict`
```sql
INSERT INTO tasks (title, description, goal_id, trigger_condition, due_date, assigned_to)
VALUES (%s, %s, %s, %s, %s, %s)
RETURNING *
```

#### `update_task(self, task_id: str, **fields) -> dict`
Valid fields: `title`, `description`, `status`, `goal_id`, `trigger_condition`, `due_date`, `assigned_to`, `result`.
When `status='done'` is in fields, also set `completed_at=NOW()`.
Build SET clause dynamically. Same pattern as `update_goal`.
```sql
UPDATE tasks SET {set_clause} WHERE id = %s RETURNING *
```

#### `list_tasks(self, goal_id: str = None, status: str = None, assigned_to: str = None) -> list[dict]`
Build WHERE clause from non-None args.
```sql
SELECT * FROM tasks [WHERE ...] ORDER BY created_at
```

#### `get_triggered_tasks(self) -> list[dict]`
```sql
SELECT * FROM tasks WHERE status = 'pending' AND trigger_condition IS NOT NULL
```

#### `get_due_tasks(self) -> list[dict]`
```sql
SELECT * FROM tasks WHERE status = 'pending' AND due_date IS NOT NULL AND due_date < NOW()
```

#### `add_progress(self, goal_id: str, note: str, source: str = 'user') -> dict`
```sql
INSERT INTO goal_progress (goal_id, note, source) VALUES (%s, %s, %s) RETURNING *
```

#### `get_progress(self, goal_id: str, limit: int = 10) -> list[dict]`
```sql
SELECT * FROM goal_progress WHERE goal_id = %s ORDER BY created_at DESC LIMIT %s
```

#### `get_active_goals_summary(self) -> str`
```sql
SELECT g.title, g.priority, g.deadline,
       COUNT(t.id) AS total_tasks,
       COUNT(t.id) FILTER (WHERE t.status = 'done') AS done_tasks
FROM goals g
LEFT JOIN tasks t ON t.goal_id = g.id
WHERE g.status = 'active'
GROUP BY g.id
ORDER BY g.priority ASC, g.created_at
```
Format each row as: `Цель [P{priority}]: "{title}" (дедлайн: {deadline or 'нет'}, задач: {done}/{total})`
Join with `\n`. Return `""` if no active goals.

#### `create_notification(self, type: str, payload: dict) -> dict`
```python
import json
```
```sql
INSERT INTO notifications (type, payload) VALUES (%s, %s::jsonb) RETURNING *
```
Pass `json.dumps(payload)` for the jsonb value.

#### `get_pending_notifications(self) -> list[dict]`
```sql
SELECT * FROM notifications WHERE read = FALSE ORDER BY created_at
```

#### `mark_notifications_read(self, ids: list[str]) -> None`
```sql
UPDATE notifications SET read = TRUE WHERE id = ANY(%s)
```

**Done when:** All methods implemented, file follows permission_repo.py patterns exactly.

---

### 1.3 Add GoalRepo to DbGateway

**File:** `src/backend/infrastructure/repositories/postgres/__init__.py`

Add import: `from backend.infrastructure.repositories.postgres.goal_repo import GoalRepo`

Change class to: `class DbGateway(KnowledgeRepo, EnvironmentRepo, UserRepo, MessageRepo, RunLogRepo, PermissionRepo, GoalRepo):`

**Done when:** `DbGateway()` instances expose all GoalRepo methods.

---

## Phase 2 — Context Injection

### 2.1 Add goals loading to conversation context

**File:** `src/backend/brain/controllers/conversation.py`

In `_ConversationContext.__init__`, add: `self.goals_summary = ""`

Add method:
```python
def load_goals(self):
    if self.auth.role == "admin":
        self.goals_summary = self.db.get_active_goals_summary()
```

In the `handle()` function (line ~148), after `ctx.load_knowledge()`, add: `ctx.load_goals()`

### 2.2 Add goals section to system prompt

**File:** `src/backend/brain/controllers/conversation.py`

Modify `_build_system_prompt` signature — add parameter `goals_summary: str = ""` after `conversation_history`.

Add after the knowledge section line (after `parts.append(_optional_section("Контекст", knowledge))`):
```python
parts.append(_optional_section("Мои цели и задачи", goals_summary))
```

Update the call in `handle()`:
```python
system_prompt = _build_system_prompt(
    auth.ctx.env, ctx.user_context, ctx.knowledge,
    ctx.history, goals_summary=ctx.goals_summary,
)
```

**Done when:** Admin conversations include active goals in system prompt. Non-admin conversations are unchanged. If no active goals, section is omitted.

---

## Phase 3 — Goals Tool

### 3.1 Create goals tool

**File:** `src/backend/brain/tools/goals.py`

Factory: `make_goals_tool(db, gemini) -> Tool`

**Tool dataclass fields:**
- `name`: `"goals"`
- `description`: `"Управление целями и задачами: создать цель, декомпозировать на задачи, отслеживать прогресс, обновить статус"`
- `parameters`: see JSON schema below
- `fn`: the handler function
- `permissions`: `{}` (DB-driven via tool_permissions table)
- `slash_command`: `None`
- `examples`: `["какие у меня цели?", "создай цель", "разбей цель на задачи", "статус цели"]`
- `nl_routable`: `True`
- `conversational`: `True`

**Parameters JSON Schema:**
```python
{
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["list", "create", "update", "plan", "progress", "status"],
            "description": "list=все цели, create=новая цель, update=обновить цель/задачу, plan=декомпозировать на задачи, progress=записать прогресс, status=подробный статус"
        },
        "title": {"type": "string", "description": "Название (для create)"},
        "description": {"type": "string", "description": "Описание (для create)"},
        "goal_id": {"type": "string", "description": "UUID цели"},
        "task_id": {"type": "string", "description": "UUID задачи (для update)"},
        "priority": {"type": "integer", "description": "1-5, 1=высший"},
        "deadline": {"type": "string", "description": "YYYY-MM-DD"},
        "status": {"type": "string", "description": "Новый статус"},
        "note": {"type": "string", "description": "Текст прогресса"}
    },
    "required": ["action"]
}
```

**Handler function `fn(args, ctx)`** — dispatch by `args["action"]`:

**`list`:**
```python
goals = db.list_goals(status=args.get("status"))
return {"goals": goals}
```

**`create`:**
```python
title = args.get("title")
if not title:
    return {"error": "Нужно указать title"}
goal = db.create_goal(
    title=title,
    description=args.get("description"),
    priority=args.get("priority", 3),
    deadline=args.get("deadline"),
)
return {"goal": goal, "confirmation": "Цель создана"}
```

**`update`:**
```python
# Build update fields from args (only non-None values)
update_fields = {}
for key in ("title", "description", "status", "priority", "deadline"):
    if args.get(key) is not None:
        update_fields[key] = args[key]
if not update_fields:
    return {"error": "Нечего обновлять"}

if args.get("task_id"):
    # Also allow: "result", "trigger_condition", "due_date", "assigned_to" for tasks
    for key in ("result", "trigger_condition", "due_date", "assigned_to"):
        if args.get(key) is not None:
            update_fields[key] = args[key]
    updated = db.update_task(args["task_id"], **update_fields)
elif args.get("goal_id"):
    updated = db.update_goal(args["goal_id"], **update_fields)
else:
    return {"error": "Нужен goal_id или task_id"}
return {"updated": updated}
```

**`plan`:**
```python
goal_id = args.get("goal_id")
if not goal_id:
    return {"error": "Нужен goal_id"}
goal = db.get_goal(goal_id)
if not goal:
    return {"error": "Цель не найдена"}
existing_tasks = db.list_tasks(goal_id=goal_id)
existing_text = "\n".join(f"- [{t['status']}] {t['title']}" for t in existing_tasks) or "(нет)"

prompt = load_template("goals/decompose-goal.md", {
    "TITLE": goal["title"],
    "DESCRIPTION": goal.get("description") or "(нет)",
    "PRIORITY": str(goal["priority"]),
    "DEADLINE": str(goal.get("deadline") or "нет"),
    "EXISTING_TASKS": existing_text,
})
result = gemini.call(prompt)
tasks_data = result.get("tasks", [])
created = []
for t in tasks_data:
    task = db.create_task(
        title=t["title"],
        description=t.get("description"),
        goal_id=goal_id,
        trigger_condition=t.get("trigger_condition"),
        assigned_to=t.get("assigned_to", "user"),
    )
    created.append(task)
return {"tasks_created": created}
```

**`progress`:**
```python
goal_id = args.get("goal_id")
note = args.get("note")
if not goal_id or not note:
    return {"error": "Нужны goal_id и note"}
entry = db.add_progress(goal_id, note, source="user")
return {"progress": entry, "confirmation": "Прогресс записан"}
```

**`status`:**
```python
goal_id = args.get("goal_id")
if not goal_id:
    return {"error": "Нужен goal_id"}
goal = db.get_goal(goal_id)
if not goal:
    return {"error": "Цель не найдена"}
tasks = db.list_tasks(goal_id=goal_id)
progress = db.get_progress(goal_id, limit=5)
return {"goal": goal, "tasks": tasks, "recent_progress": progress}
```

**Import at top of file:**
```python
from backend.brain.prompt_loader import load_template
from backend.brain.tool import Tool, ToolContext
```

**Done when:** Tool handles all 6 actions, returns structured dicts, follows search.py/teach.py patterns.

---

### 3.2 Create decompose-goal template

**File:** `src/backend/templates/goals/decompose-goal.md`

Create directory `src/backend/templates/goals/` first.

```markdown
Разбей цель на конкретные задачи.

## Цель
Название: {{TITLE}}
Описание: {{DESCRIPTION}}
Приоритет: {{PRIORITY}}
Дедлайн: {{DEADLINE}}

## Существующие задачи
{{EXISTING_TASKS}}

## Правила
- Каждая задача должна быть конкретной и проверяемой
- assigned_to: "user" для задач, требующих человека (встречи, финальные решения, утверждения); "agent" для того, что может сделать AI (анализ, черновики, поиск, мониторинг)
- trigger_condition: текстовое условие активации (например "когда будет готов черновик статьи", "после завершения задачи X") или null если задачу можно начинать сразу
- Не дублируй существующие задачи
- 3-7 задач обычно достаточно

Верни JSON:
{"tasks": [{"title": "...", "description": "...", "assigned_to": "user|agent", "trigger_condition": "..." или null}]}
```

**Done when:** Template exists, uses `{{VAR}}` syntax compatible with `load_template`.

---

### 3.3 Register tool in wiring

**File 1:** `src/backend/brain/tools/__init__.py`

Add import line: `from backend.brain.tools.goals import make_goals_tool`

Add to `__all__` list: `"make_goals_tool",`

**File 2:** `src/backend/wiring.py`

Add `make_goals_tool` to the import line from `backend.brain.tools`:
```python
from backend.brain.tools import (
    ...,
    make_goals_tool,
)
```

In `_register_core_tools()`, add after `register_tool(make_permissions_tool(db))`:
```python
register_tool(make_goals_tool(db, gemini))
```

Note: `_register_core_tools` currently receives `(genai, memory, retriever, gemini, db)`. The `gemini` and `db` params are already available.

**Done when:** `goals` appears in `TOOLS` dict at startup, routable for admin users.

---

## Phase 4 — Goal Monitor (Cron)

### 4.1 Create GoalMonitor

**File:** `src/backend/commands/goal_monitor.py`

```python
"""Background goal monitoring — triggers, deadlines, agent task execution."""

from __future__ import annotations

import logging
from datetime import datetime

from backend.brain.prompt_loader import load_template
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from backend.infrastructure.repositories.postgres import DbGateway

logger = logging.getLogger(__name__)
```

**Class `GoalMonitor`:**

```python
class GoalMonitor:
    def __init__(self, db: DbGateway, gemini: GeminiGateway):
        self._db = db
        self._gemini = gemini

    def run(self) -> dict:
        triggered = self._check_triggers()
        overdue = self._check_deadlines()
        agent_results = self._execute_agent_tasks()
        return {
            "triggered": len(triggered),
            "overdue": len(overdue),
            "agent_completed": len(agent_results),
        }
```

#### `_check_triggers(self) -> list[dict]`

1. `tasks = self._db.get_triggered_tasks()`
2. For each task:
   a. Load parent goal if `task["goal_id"]`: `goal = self._db.get_goal(task["goal_id"])`
   b. Load sibling tasks (same goal) for dependency context: `siblings = self._db.list_tasks(goal_id=task["goal_id"])` — format as `[done] Title A\n[pending] Title B`
   c. Build prompt from template `goals/evaluate-trigger.md` with:
      - `TASK_TITLE`: `task["title"]`
      - `TASK_DESCRIPTION`: `task.get("description") or "(нет)"`
      - `TRIGGER_CONDITION`: `task["trigger_condition"]`
      - `GOAL_CONTEXT`: `f"{goal['title']}: {goal.get('description', '')}"` if goal else `"(нет цели)"`
      - `SIBLING_TASKS`: formatted sibling list or `"(нет)"`
      - `CURRENT_DATE`: `datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")`
   d. Call `self._gemini.call(prompt)` → expect `{"triggered": bool, "reason": str}`
   e. If `triggered == True`:
      - `self._db.update_task(task["id"], status="in_progress")`
      - `self._db.add_progress(task["goal_id"], f"Задача '{task['title']}' активирована: {reason}", source="auto")` (only if goal_id)
      - `self._db.create_notification("task_triggered", {"task_id": str(task["id"]), "task_title": task["title"], "reason": reason})`
3. Return list of triggered task dicts
4. Wrap each task evaluation in try/except — log and continue on failure

#### `_check_deadlines(self) -> list[dict]`

1. `tasks = self._db.get_due_tasks()`
2. For each task:
   - `self._db.create_notification("task_overdue", {"task_id": str(task["id"]), "task_title": task["title"], "due_date": str(task["due_date"])})`
   - Update task status to `"blocked"` (overdue = needs attention)
3. Return list of overdue task dicts

#### `_execute_agent_tasks(self) -> list[dict]`

1. `tasks = self._db.list_tasks(assigned_to="agent", status="in_progress")`
2. For each task:
   a. Load parent goal if available
   b. Build prompt from template `goals/execute-task.md` with:
      - `TASK_TITLE`: task title
      - `TASK_DESCRIPTION`: task description or "(нет)"
      - `GOAL_CONTEXT`: goal info or "(нет цели)"
   c. Call `self._gemini.call(prompt)` → expect `{"result": str, "completed": bool}`
   d. If `completed`:
      - `self._db.update_task(task["id"], status="done", result=result_text)`
      - `self._db.add_progress(goal_id, f"Агент завершил: {task['title']}", source="agent")` (if goal_id)
      - `self._db.create_notification("task_completed", {"task_id": str(task["id"]), "task_title": task["title"], "result": result_text[:500]})`
   e. If not completed:
      - `self._db.update_task(task["id"], result=result_text)` (save partial progress)
3. Wrap each task in try/except — log and continue
4. Return list of result dicts

**Important constraint:** `_execute_agent_tasks` does NOT have access to tools. The agent produces text results only (analysis, drafts, recommendations). Tool access in cron is a future feature with explicit scoping.

**Done when:** Class works standalone with db + gemini. No side effects beyond DB writes and notifications.

---

### 4.2 Create `goals/evaluate-trigger.md`

**File:** `src/backend/templates/goals/evaluate-trigger.md`

```markdown
Определи, выполнено ли условие активации задачи.

Текущая дата: {{CURRENT_DATE}}

## Задача
{{TASK_TITLE}}
{{TASK_DESCRIPTION}}

## Условие активации
{{TRIGGER_CONDITION}}

## Контекст цели
{{GOAL_CONTEXT}}

## Другие задачи этой цели
{{SIBLING_TASKS}}

## Правила
- Оцени на основе имеющейся информации и текущей даты
- Зависимости от других задач: проверь их статус в списке выше
- Временные условия ("после 1 апреля"): сравни с текущей датой
- Если условие требует внешних данных, которых нет — верни triggered: false
- Будь консервативен: лучше не активировать задачу преждевременно

Верни JSON: {"triggered": true/false, "reason": "краткое объяснение"}
```

---

### 4.3 Create `goals/execute-task.md`

**File:** `src/backend/templates/goals/execute-task.md`

```markdown
Выполни задачу. Ты — AI-ассистент издателя Republic.

## Задача
Название: {{TASK_TITLE}}
Описание: {{TASK_DESCRIPTION}}

## Цель (контекст)
{{GOAL_CONTEXT}}

## Правила
- Выполни задачу в рамках своих возможностей: анализ, текст, рекомендации, черновики
- Если задача требует действий во внешних системах (отправить email, опубликовать) — опиши что сделать, но отметь completed: false
- Если задача — исследование или анализ — проведи его и отметь completed: true
- Будь конкретен и полезен, без общих фраз

Верни JSON: {"result": "результат выполнения", "completed": true/false}
```

---

### 4.4 Wire GoalMonitor into run.py

**File:** `src/backend/run.py`

Replace the current content with:

```python
"""Backend API entry point with scheduled tasks."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

import uvicorn

from backend.api import app, db, gemini

logger = logging.getLogger(__name__)

GOAL_MONITOR_INTERVAL = int(os.getenv("GOAL_MONITOR_INTERVAL", "3600"))


async def _goal_monitor_loop():
    """Periodic goal monitoring: triggers, deadlines, agent tasks."""
    from backend.commands.goal_monitor import GoalMonitor
    monitor = GoalMonitor(db, gemini)
    logger.info("Goal monitor started (interval %ds)", GOAL_MONITOR_INTERVAL)
    await asyncio.sleep(60)  # initial delay to let the system stabilize
    while True:
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, monitor.run)
            logger.info("Goal monitor: %s", result)
        except Exception:
            logger.exception("Goal monitor error")
        await asyncio.sleep(GOAL_MONITOR_INTERVAL)


@asynccontextmanager
async def lifespan(_app):
    """Start background tasks on API startup."""
    tasks = [
        asyncio.create_task(_goal_monitor_loop()),
    ]
    yield
    for t in tasks:
        t.cancel()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    app.router.lifespan_context = lifespan
    uvicorn.run(app, host="0.0.0.0", port=8100)


if __name__ == "__main__":
    main()
```

**Key details:**
- Import `db` and `gemini` from `api.py` — they are module-level globals created by `create_brain()`
- Use `run_in_executor` to run sync DB/Gemini code in a thread pool
- 60-second initial delay before first run
- `GoalMonitor` import is inside the function to avoid circular imports
- `GOAL_MONITOR_INTERVAL` defaults to 3600 (1 hour), configurable via env var

**Done when:** Backend starts the goal monitor loop on boot.

---

## Phase 5 — Notification Channel (Backend → Bot)

### 5.1 Add notification endpoint to API

**File:** `src/backend/api.py`

Add after the permissions endpoints block:

```python
# --- Notifications ---

@app.get("/notifications/pending")
def pending_notifications() -> BrainResponse:
    items = db.get_pending_notifications()
    if items:
        ids = [str(n["id"]) for n in items]
        db.mark_notifications_read(ids)
    return BrainResponse(result=items)
```

**Done when:** `GET /notifications/pending` returns unread notifications and marks them read atomically.

---

### 5.2 Add backend_client method

**File:** `src/client/telegram_bot/backend_client.py`

Add function (follow existing function patterns in that file — check what `fetch_unread()` looks like and replicate):

```python
async def get_pending_notifications() -> list[dict]:
    resp = await _get("/notifications/pending")
    return _unwrap(resp) or []
```

Note: Check the actual HTTP helper function names in `backend_client.py`. The file likely uses `_get()` or `_request()` helpers. Match the existing pattern exactly.

**Done when:** Bot can call `backend_client.get_pending_notifications()`.

---

### 5.3 Create goal notification listener

**File:** `src/client/telegram_bot/handlers/goal_notifications.py`

Follow `email_listener.py` pattern exactly:

```python
"""Goal notification background task."""

from __future__ import annotations

import asyncio
import logging
import os

from telegram_bot import backend_client
from telegram_bot.bot_helpers import get_admin_ids, get_bot

logger = logging.getLogger(__name__)

__all__ = ["goal_notification_task"]

_FORMATS = {
    "task_triggered": "⚡ Задача активирована: {task_title}\nПричина: {reason}",
    "task_overdue": "⏰ Задача просрочена: {task_title}\nДедлайн: {due_date}",
    "task_completed": "✅ Агент выполнил: {task_title}\nРезультат: {result}",
}


def _format_notification(n: dict) -> str:
    ntype = n.get("type", "")
    payload = n.get("payload", {})
    template = _FORMATS.get(ntype)
    if template:
        return template.format(**payload)
    return f"📋 {ntype}: {payload}"


async def goal_notification_task() -> None:
    """Background task: poll for goal notifications, send to admin."""
    admin_ids = get_admin_ids()
    if not admin_ids:
        logger.warning("No admin IDs, goal notifications disabled")
        return
    admin_id = next(iter(admin_ids))
    poll_interval = int(os.getenv("GOAL_NOTIFICATION_INTERVAL", "300"))
    bot = get_bot()
    logger.info("Goal notification listener started (poll every %ds)", poll_interval)
    while True:
        try:
            notifications = await backend_client.get_pending_notifications()
            if notifications:
                for n in notifications:
                    text = _format_notification(n)
                    await bot.send_message(admin_id, text)
        except Exception as e:
            logger.exception("Goal notification error: %s", e)
        await asyncio.sleep(poll_interval)
```

**Note on `get_bot()`:** Check how `email_listener.py` gets the bot instance for sending messages. It uses `_send_support_draft` and `_send_editorial` helpers from `support_handlers.py`. Check how those send messages and replicate the pattern. If bot instance is obtained via a global or import, do the same. If messages are sent via a helper, create a similar helper or send directly.

**Done when:** Bot polls `/notifications/pending` every 5 minutes (default) and sends formatted messages to admin.

---

### 5.4 Register in bot startup

**File:** Check how `email_listener_task` is registered in the bot's startup sequence. Find the file that calls `email_listener_task()` and add `goal_notification_task()` alongside it.

Likely file: `src/client/telegram_bot/main.py` or similar entry point.

Add import: `from telegram_bot.handlers.goal_notifications import goal_notification_task`

Add to the background tasks list (wherever `email_listener_task` is added):
```python
asyncio.create_task(goal_notification_task())
```

**Done when:** Bot starts the goal notification polling loop on startup.

---

## Phase 6 — Tests

### 6.1 Test goal_repo

**File:** `tests/test_goal_repo.py`

Tests to write (check existing test files for fixture/setup patterns — likely use a real DB or mock):

- [ ] `test_create_goal` — create with title + priority, verify returned dict has all fields, status='active'
- [ ] `test_update_goal_status` — create, update status to 'done', verify status changed and updated_at > created_at
- [ ] `test_update_goal_invalid_field` — update with invalid field name, expect ValueError
- [ ] `test_list_goals_filters` — create 2 active + 1 done, list(status='active') returns 2, list() returns 3
- [ ] `test_create_task_with_goal` — create goal, create task with goal_id, verify task.goal_id matches
- [ ] `test_create_task_standalone` — create task without goal_id, verify goal_id is None
- [ ] `test_update_task_done_sets_completed_at` — update status='done', verify completed_at is not None
- [ ] `test_get_triggered_tasks` — create task with trigger_condition + task without, verify only one returned
- [ ] `test_get_due_tasks` — create task with past due_date + task with future due_date, verify only past one returned
- [ ] `test_active_goals_summary_format` — create goal with 2 tasks (1 done), verify string format matches `Цель [P3]: "..." (..., задач: 1/2)`
- [ ] `test_active_goals_summary_empty` — no goals, returns `""`
- [ ] `test_notifications_lifecycle` — create, get_pending returns it, mark_read, get_pending returns empty
- [ ] `test_progress` — add progress to goal, get_progress returns it with correct source

### 6.2 Test goals tool

**File:** `tests/test_goals_tool.py`

- [ ] `test_list_empty` — no goals, action=list returns `{"goals": []}`
- [ ] `test_create_and_list` — create via tool, list via tool, verify appears
- [ ] `test_create_missing_title` — action=create without title returns `{"error": ...}`
- [ ] `test_update_goal` — create, then update status=paused, verify
- [ ] `test_progress_action` — create goal, add progress, check status action returns it
- [ ] `test_plan_action` — mock `gemini.call` to return `{"tasks": [{"title": "T1", ...}]}`, verify tasks created in DB

---

## Phase 7 — Documentation & External TODOs

### 7.1 Update diagrams

**File:** `docs/diagrams/brain-flows.md`

Add new section after "4. Inbox Processing (Background)":

```markdown
## 5. Goal Monitor (Background)

\```
Cron (every GOAL_MONITOR_INTERVAL) ──▶ GoalMonitor.run()
                                           │
                                           ├──▶ _check_triggers()
                                           │        ├── DB: get pending tasks with trigger_condition
                                           │        ├── For each: Gemini evaluates condition
                                           │        │     └── template: goals/evaluate-trigger.md
                                           │        └── If triggered: update task → in_progress, notify
                                           │
                                           ├──▶ _check_deadlines()
                                           │        ├── DB: get pending tasks past due_date
                                           │        └── Mark blocked, notify
                                           │
                                           └──▶ _execute_agent_tasks()
                                                    ├── DB: get in_progress tasks assigned to agent
                                                    ├── For each: Gemini executes (text only)
                                                    │     └── template: goals/execute-task.md
                                                    └── Mark done/partial, notify

Notifications ──▶ DB (notifications table)
                       │
Bot polls /notifications/pending ──▶ Telegram message to admin
\```
```

Update "Component Wiring (create_brain)" section — add to Tools list:
```
│  ├── goals          (conv, routable) │
```

Add to "Conversational Tools" list:
```
- `goals` — manage goals, tasks, progress, decomposition
```

Renumber subsequent sections (QueryDB becomes 6, etc.).

### 7.2 Update external-todo.md

**File:** `autonomous/dev/external-todo.md`

```markdown
## Goals & Tasks System (Plan 12)

- [ ] Add `GOAL_MONITOR_INTERVAL` to `config/backend.env` (seconds, default 3600)
- [ ] Add `GOAL_NOTIFICATION_INTERVAL` to `config/bot.env` (seconds, default 300)
- [ ] Deploy and verify migration 007 applied (check DB for goals/tasks/notifications tables)
- [ ] Create initial goals via Telegram to verify end-to-end flow
- [ ] Teach identity intents (publisher vision, editorial direction) via /teach
- [ ] Monitor goal_monitor logs for first 48h — check trigger evaluation quality
- [ ] Tune GOAL_MONITOR_INTERVAL based on actual usage (more frequent if many trigger-based tasks)
```

---

## Implementation Order (recommended)

```
Phase 1 (1.1 → 1.2 → 1.3) — DB foundation
  ↓
Phase 3 (3.1 → 3.2 → 3.3) — Goals tool (immediately testable via chat)
  ↓
Phase 2 (2.1 → 2.2) — Context injection (quick, ~20 lines changed)
  ↓
Phase 4 (4.1 → 4.2 → 4.3 → 4.4) — Cron monitor
  ↓
Phase 5 (5.1 → 5.2 → 5.3 → 5.4) — Bot notifications
  ↓
Phase 6 (6.1 → 6.2) — Tests
  ↓
Phase 7 (7.1 → 7.2) — Docs & external TODOs
```

## Files Created (new)
- `src/backend/infrastructure/repositories/postgres/migrations/007_goals_and_tasks.sql`
- `src/backend/infrastructure/repositories/postgres/goal_repo.py`
- `src/backend/brain/tools/goals.py`
- `src/backend/templates/goals/decompose-goal.md`
- `src/backend/templates/goals/evaluate-trigger.md`
- `src/backend/templates/goals/execute-task.md`
- `src/backend/commands/goal_monitor.py`
- `src/client/telegram_bot/handlers/goal_notifications.py`
- `tests/test_goal_repo.py`
- `tests/test_goals_tool.py`

## Files Modified
- `src/backend/infrastructure/repositories/postgres/__init__.py` — add GoalRepo mixin
- `src/backend/brain/controllers/conversation.py` — load_goals + system prompt section
- `src/backend/brain/tools/__init__.py` — export make_goals_tool
- `src/backend/wiring.py` — register goals tool
- `src/backend/run.py` — goal monitor cron loop
- `src/backend/api.py` — notifications endpoint
- `src/client/telegram_bot/backend_client.py` — get_pending_notifications
- Bot main.py (find exact file) — register goal_notification_task
- `docs/diagrams/brain-flows.md` — new diagram section
- `autonomous/dev/external-todo.md` — manual steps
