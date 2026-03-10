# Dev Agent Memory

> This file accumulates context across autonomous sessions. The orchestrator updates it after each session.

## Completed

### Session 1 (Plan 12 — ALL PHASES)
Implemented the entire Goals & Tasks system in one session:

**Phase 1 — Data Layer:**
- Migration `007_goals_and_tasks.sql` (goals, tasks, goal_progress, notifications tables)
- `goal_repo.py` with 15 methods (CRUD, progress, summary, notifications)
- GoalRepo added to DbGateway MRO

**Phase 2 — Context Injection:**
- `load_goals()` on _ConversationContext (admin-only)
- Goals summary injected into system prompt after knowledge, before history

**Phase 3 — Goals Tool:**
- `goals.py` tool with 6 actions: list, create, update, plan, progress, status
- `decompose-goal.md` template for LLM-based goal decomposition
- Tool registered in wiring.py

**Phase 4 — Goal Monitor:**
- `goal_monitor.py` with _check_triggers, _check_deadlines, _execute_agent_tasks
- Two templates: evaluate-trigger.md, execute-task.md
- Cron loop in run.py (GOAL_MONITOR_INTERVAL, default 3600s)

**Phase 5 — Notifications:**
- GET /notifications/pending endpoint in api.py
- `get_pending_notifications()` in backend_client.py
- `goal_notification_task` polling listener
- Registered in bot main.py

**Phase 6 — Tests:**
- FakeDb extended with all GoalRepo in-memory methods
- 13 repo tests + 6 tool tests (175 total, all passing)

**Phase 7 — Docs:**
- brain-flows.md updated with Goal Monitor diagram
- external-todo.md updated with deployment checklist

## Known issues

_None._

## Pitfalls

- GoalRepo uses `_row_to_dict` helper (SELECT * → dict via cursor.description) — different from PermissionRepo's positional tuple unpacking
- `update_goal`/`update_task` use sentinel string `"NOW()"` to inject SQL NOW() — fragile if someone passes literal "NOW()" as data
- FakeDb goal methods replicate SQL behavior in Python — may drift if repo changes
