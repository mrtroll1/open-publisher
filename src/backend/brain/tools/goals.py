from __future__ import annotations

import logging

from backend.brain.prompt_loader import load_template
from backend.brain.tool import Tool, ToolContext

logger = logging.getLogger(__name__)


def _list(db, _gemini, args: dict) -> dict:
    goals = db.list_goals(status=args.get("status"))
    return {"goals": goals}


def _create(db, _gemini, args: dict) -> dict:
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


def _update(db, _gemini, args: dict) -> dict:
    update_fields = {}
    for key in ("title", "description", "status", "priority", "deadline"):
        if args.get(key) is not None:
            update_fields[key] = args[key]
    if not update_fields:
        return {"error": "Нечего обновлять"}
    if args.get("task_id"):
        for key in ("result", "trigger_condition", "due_date", "assigned_to"):
            if args.get(key) is not None:
                update_fields[key] = args[key]
        updated = db.update_task(args["task_id"], **update_fields)
    elif args.get("goal_id"):
        updated = db.update_goal(args["goal_id"], **update_fields)
    else:
        return {"error": "Нужен goal_id или task_id"}
    return {"updated": updated}


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


def _progress(db, _gemini, args: dict) -> dict:
    goal_id = args.get("goal_id")
    note = args.get("note")
    if not goal_id or not note:
        return {"error": "Нужны goal_id и note"}
    entry = db.add_progress(goal_id, note, source="user")
    return {"progress": entry, "confirmation": "Прогресс записан"}


def _status(db, _gemini, args: dict) -> dict:
    goal_id = args.get("goal_id")
    if not goal_id:
        return {"error": "Нужен goal_id"}
    goal = db.get_goal(goal_id)
    if not goal:
        return {"error": "Цель не найдена"}
    tasks = db.list_tasks(goal_id=goal_id)
    progress = db.get_progress(goal_id, limit=5)
    return {"goal": goal, "tasks": tasks, "recent_progress": progress}


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


_ACTIONS = {
    "list": _list,
    "create": _create,
    "update": _update,
    "plan": _plan,
    "progress": _progress,
    "status": _status,
    "launch": _launch,
}


def make_goals_tool(db, gemini) -> Tool:
    def fn(args: dict, _ctx: ToolContext) -> dict:
        action = args.get("action", "list")
        handler = _ACTIONS.get(action)
        if not handler:
            return {"error": f"Unknown action: {action}"}
        return handler(db, gemini, args)

    return Tool(
        name="goals",
        description="Управление целями и задачами: создать цель, декомпозировать на задачи, отслеживать прогресс, обновить статус",
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "create", "update", "plan", "progress", "status", "launch"],
                    "description": "list=все цели, create=новая цель, update=обновить цель/задачу, plan=декомпозировать на задачи, progress=записать прогресс, status=подробный статус, launch=создать цель и сразу декомпозировать",
                },
                "title": {"type": "string", "description": "Название (для create)"},
                "description": {"type": "string", "description": "Описание (для create)"},
                "goal_id": {"type": "string", "description": "UUID цели"},
                "task_id": {"type": "string", "description": "UUID задачи (для update)"},
                "priority": {"type": "integer", "description": "1-5, 1=высший"},
                "deadline": {"type": "string", "description": "YYYY-MM-DD"},
                "status": {"type": "string", "description": "Новый статус"},
                "note": {"type": "string", "description": "Текст прогресса"},
            },
            "required": ["action"],
        },
        fn=fn,
        permissions={},
        slash_command=None,
        examples=["какие у меня цели?", "создай цель", "разбей цель на задачи", "статус цели"],
        nl_routable=True,
        conversational=True,
    )
