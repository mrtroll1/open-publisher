"""Background goal monitoring — triggers, deadlines, agent task execution."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from backend.brain.prompt_loader import load_template
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from backend.infrastructure.repositories.postgres import DbGateway

if TYPE_CHECKING:
    from backend.brain.agent_executor import AgentTaskExecutor

logger = logging.getLogger(__name__)


class GoalMonitor:
    def __init__(self, db: DbGateway, gemini: GeminiGateway,
                 agent_executor: AgentTaskExecutor | None = None):
        self._db = db
        self._gemini = gemini
        self._executor = agent_executor

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
                        self._db.add_progress(task["goal_id"], f"Задача активирована: {task['title']}", source="auto")
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
                        continue
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
