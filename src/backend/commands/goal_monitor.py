"""Background goal monitoring — triggers, deadlines, agent task execution."""

from __future__ import annotations

import logging
from datetime import datetime

from backend.brain.prompt_loader import load_template
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from backend.infrastructure.repositories.postgres import DbGateway

logger = logging.getLogger(__name__)


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

    def _check_triggers(self) -> list[dict]:
        tasks = self._db.get_triggered_tasks()
        triggered = []
        for task in tasks:
            try:
                goal = self._db.get_goal(task["goal_id"]) if task.get("goal_id") else None
                siblings = self._db.list_tasks(goal_id=task["goal_id"]) if task.get("goal_id") else []
                sibling_lines = "\n".join(
                    f"- {t['title']} [{t['status']}]" for t in siblings if t["id"] != task["id"]
                )
                goal_context = f"{goal['title']}\n{goal.get('description') or ''}" if goal else "(нет)"
                prompt = load_template("goals/evaluate-trigger.md", {
                    "TASK_TITLE": task["title"],
                    "TASK_DESCRIPTION": task.get("description") or "",
                    "TRIGGER_CONDITION": task.get("trigger_condition") or "",
                    "GOAL_CONTEXT": goal_context,
                    "SIBLING_TASKS": sibling_lines or "(нет)",
                    "CURRENT_DATE": datetime.utcnow().strftime("%Y-%m-%d"),
                })
                result = self._gemini.call(prompt)
                if result.get("triggered"):
                    self._db.update_task(task["id"], status="in_progress")
                    if task.get("goal_id"):
                        self._db.add_progress(task["goal_id"], f"Задача активирована: {task['title']}", source="monitor")
                    self._db.create_notification("task_triggered", {
                        "task_id": str(task["id"]),
                        "task_title": task["title"],
                        "reason": result.get("reason", ""),
                    })
                    triggered.append(task)
            except Exception:
                logger.exception("Failed to check trigger for task %s", task.get("id"))
        return triggered

    def _check_deadlines(self) -> list[dict]:
        tasks = self._db.get_due_tasks()
        overdue = []
        for task in tasks:
            try:
                self._db.create_notification("task_overdue", {
                    "task_id": str(task["id"]),
                    "task_title": task["title"],
                    "due_date": str(task.get("due_date", "")),
                })
                self._db.update_task(task["id"], status="blocked")
                overdue.append(task)
            except Exception:
                logger.exception("Failed to process overdue task %s", task.get("id"))
        return overdue

    def _execute_agent_tasks(self) -> list[dict]:
        tasks = self._db.list_tasks(status="in_progress", assigned_to="agent")
        results = []
        for task in tasks:
            try:
                goal = self._db.get_goal(task["goal_id"]) if task.get("goal_id") else None
                goal_context = f"{goal['title']}\n{goal.get('description') or ''}" if goal else "(нет)"
                prompt = load_template("goals/execute-task.md", {
                    "TASK_TITLE": task["title"],
                    "TASK_DESCRIPTION": task.get("description") or "",
                    "GOAL_CONTEXT": goal_context,
                })
                result = self._gemini.call(prompt)
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
