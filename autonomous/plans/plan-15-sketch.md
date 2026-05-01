# Plan 15 Sketch: Recurring & Event-Driven Autonomous Tasks

> What's missing for cron-like scheduling, event-driven triggers, and robust long-running autonomous workflows.

## Current State (after Plan 14)

The goal/task system handles: create goal → decompose → agent executes with tools → checkpoint → approve → continue. Three activation paths work today:

1. **`launch`** — first task auto-activated on creation
2. **`depends_on`** — previous task completes → next activates
3. **`trigger_condition`** — LLM evaluates free text against date + sibling statuses

All three converge to: `status=in_progress, assigned_to=agent` → GoalMonitor picks up → AgentTaskExecutor runs ReAct loop.

## What's Missing

### 1. Recurring Tasks (Critical)

**Problem:** Tasks move `pending → in_progress → done` and stay done forever. No way to express "every morning" or "weekly on Monday."

**After a triggered task completes:**
```
pending → (trigger fires) → in_progress → (agent executes) → done → 💀 never runs again
```

**What's needed:** After a trigger-based task completes, it should reset to `pending` so it re-evaluates on the next monitor tick. Two options:

**Option A — Auto-reset on completion (simplest):**
- If task has `trigger_condition` AND no `depends_on`: after marking `done`, immediately reset to `pending`
- Previous result stored in `goal_progress`, not lost
- Risk: rapid re-triggering if trigger condition is still true. Mitigation: add `last_triggered_at` field, template gets it as context

**Option B — Recurrence field on tasks:**
- Add `recurrence TEXT` field (e.g., `"daily"`, `"weekday"`, `"weekly:monday"`, `"interval:6h"`)
- Deterministic evaluation (no LLM needed): compare against `last_triggered_at`
- `trigger_condition` stays for complex conditions, `recurrence` for simple schedules
- Cleaner separation: schedule (when to run) vs condition (whether to run)

**Recommendation:** Option B. Recurrence is deterministic — using an LLM to check "is it Monday?" is wasteful. `recurrence` for schedule, `trigger_condition` for complex conditions. Both optional, evaluated independently.

**Schema change:**
```sql
ALTER TABLE tasks ADD COLUMN recurrence TEXT;  -- "daily", "weekday", "weekly:mon", "interval:6h"
ALTER TABLE tasks ADD COLUMN last_triggered_at TIMESTAMPTZ;
```

**Monitor change:** New `_check_recurrence()` method that evaluates deterministically, no LLM call.

### 2. Time Precision

**Problem:** `evaluate-trigger.md` receives `CURRENT_DATE` (date only, UTC). Can't express "every morning at 9am CET."

**What's needed:**
- Pass `CURRENT_DATETIME` with timezone (CET, matching the user's timezone already used in other templates)
- For `recurrence` field: deterministic time check with timezone awareness
- Consider: user's timezone stored in config (it's already CET in templates)

### 3. Monitor Interval

**Problem:** `GOAL_MONITOR_INTERVAL=3600` (1 hour). Worst case: task completes at 9:01, next task doesn't start until 10:01.

**What's needed for different use cases:**
- **Pipelines (depends_on chains):** Should be fast. 5-10 minutes is acceptable.
- **Daily recurring tasks:** 1 hour is fine.
- **Event-driven (future):** Needs webhook or shorter interval.

**Recommendation:** Reduce default to 600 (10 min). Add a fast-path: when `_execute_agent_tasks()` completes a task, immediately check if the next task in chain can start (don't wait for next tick). This makes pipelines snappy without increasing global polling frequency.

### 4. Event-Driven Triggers

**Problem:** No way to trigger tasks based on external events like "channel scrape completed" or "email received about topic X."

**What's needed (future, not urgent):**
- Emit events from existing background commands: `scrape_channels` → `event:scrape_complete`, `process_inbox` → `event:email_classified`
- New task field or trigger_condition pattern: `"event:scrape_complete AND domain=competitors"`
- GoalMonitor subscribes to events (or events directly activate matching tasks)

**Simplest version:** Just use a DB table `events` (type, payload, created_at). Scraper writes an event row when done. `_check_triggers` query also checks recent events. Template gets event data as context.

**Even simpler:** The channel scraper already stores digests in `unit_of_knowledge`. A trigger condition like "когда появится новый дайджест" can be evaluated by the LLM checking `last_summarized_at` on the environment. This works today with the existing trigger system, just needs the template to have access to more context.

### 5. Task Timeout & Failure Recovery

**Problem:** Agent tasks run to completion (or failure) with no timeout. A stuck task blocks the pipeline.

**What's needed:**
- Max execution time per task (e.g., 10 minutes)
- If exceeded: mark as `blocked`, notify admin
- Failed tasks (exception in executor): currently stay `in_progress` forever
- Need: auto-retry once, then escalate to `blocked` + notification

**Schema change:**
```sql
ALTER TABLE tasks ADD COLUMN retry_count INT NOT NULL DEFAULT 0;
```

**Monitor change:** In `_execute_agent_tasks`, if task has been `in_progress` for > threshold without progress, mark blocked.

### 6. Auto-Complete Goals

**Problem:** Goal stays `active` even when all tasks are `done`. User must manually close it.

**What's needed:** After each task completion, check if all tasks in the goal are `done`. If yes, update goal to `done` and notify.

**Simple addition to GoalMonitor:**
```python
def _check_goal_completion(self):
    for goal in self._db.list_goals(status="active"):
        tasks = self._db.list_tasks(goal_id=goal["id"])
        if tasks and all(t["status"] == "done" for t in tasks):
            self._db.update_goal(goal["id"], status="done")
            self._db.create_notification("goal_completed", {...})
```

Exception: goals with recurring tasks should never auto-complete.

### 7. Duplicate Execution Guard

**Problem:** If GoalMonitor takes longer than the interval (e.g., agent task runs 2 hours on a 1-hour interval), the next tick may re-execute the same task.

**What's needed:** Simple lock — skip tick if previous is still running. Already partially handled since `run_in_executor` is awaited, but worth making explicit:

```python
_running = False

async def _goal_monitor_loop():
    global _running
    while True:
        await asyncio.sleep(GOAL_MONITOR_INTERVAL)
        if _running:
            logger.warning("GoalMonitor still running, skipping tick")
            continue
        _running = True
        try:
            ...
        finally:
            _running = False
```

### 8. Pipeline Fast-Path

**Problem:** In a 5-task pipeline, each task waits for the next monitor tick to activate. With 1-hour interval: 5 hours minimum. Even with 10 min: 50 minutes of waiting.

**What's needed:** After a task completes, immediately activate and execute the next task in chain (if it's agent-assigned). No need to wait for next tick.

**Implementation:** In `_execute_agent_tasks`, after marking a task done, check if the next depends_on task exists and is agent-assigned. If so, execute it in the same loop iteration.

```python
# After marking task done:
next_tasks = [t for t in goal_tasks if t.get("depends_on") == task["id"] and t["status"] == "pending"]
for nt in next_tasks:
    if nt["assigned_to"] == "agent":
        self._db.update_task(nt["id"], status="in_progress")
        # Execute immediately (recursive or add to queue)
```

This makes pipelines execute as fast as the LLM can work, only pausing at checkpoints (user tasks).

## Priority Order

| # | Feature | Impact | Effort |
|---|---------|--------|--------|
| 1 | **Recurring tasks** (recurrence field + auto-reset) | Unlocks daily briefings, monitoring | Medium |
| 2 | **Pipeline fast-path** (immediate next-task execution) | Pipelines finish in minutes, not hours | Small |
| 3 | **Auto-complete goals** | Cleanliness, notifications | Small |
| 4 | **Duplicate execution guard** | Prevents double-runs | Small |
| 5 | **Task timeout + retry** | Robustness for stuck tasks | Medium |
| 6 | **Time precision** (datetime + timezone in triggers) | Better scheduling accuracy | Small |
| 7 | **Reduce monitor interval** to 10 min | Faster everything | Config change |
| 8 | **Event-driven triggers** | Reactive workflows | Large (future) |

## Files That Would Change

- `migrations/014_recurring_tasks.sql` — `recurrence`, `last_triggered_at`, `retry_count`
- `goal_repo.py` — new fields in create/update, `get_recurring_tasks()` query
- `goal_monitor.py` — `_check_recurrence()`, fast-path execution, auto-complete, guard, timeout
- `evaluate-trigger.md` — CURRENT_DATETIME with timezone
- `decompose-goal.md` — recurrence field in output schema
- `goals.py` tool — expose recurrence in create/update
- `config/backend.env` — reduce GOAL_MONITOR_INTERVAL
- `conftest.py` — FakeDb updates
- Tests for all new behavior
