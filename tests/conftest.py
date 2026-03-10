"""Shared fixtures — fakes for the natural boundaries of the system."""
# ruff: noqa: E402

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

# Stub required env vars before any backend imports trigger config.py
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_REQUIRED = {
    "CONFIG_DIR": os.path.join(_PROJECT_ROOT, "config"),
    "ADMIN_TELEGRAM_TAG": "@test_admin",
    "GOOGLE_SERVICE_ACCOUNT_FILE": "/dev/null",
    "CONTRACTORS_SHEET_ID": "fake",
    "REPUBLIC_SITE_URL": "https://test.example.com",
    "REDEFINE_SITE_URL": "https://test2.example.com",
}
for k, v in _REQUIRED.items():
    os.environ.setdefault(k, v)

from unittest.mock import MagicMock

import pytest

from backend.brain.tool import TOOLS, Tool

# ── Fake DB ──────────────────────────────────────────────────────────


class FakeDb:
    """Minimal stand-in for DbGateway — returns canned data."""

    def __init__(self):
        self.environments: dict[str, dict] = {}
        self.environments_by_chat: dict[int, dict] = {}
        self.users: dict[int, dict] = {}
        self.messages: list[dict] = []
        self.run_logs: list[dict] = []
        self.permissions: dict[tuple[str, str], list[str]] = {}  # (tool, env) -> roles
        self.goals: dict[str, dict] = {}
        self.tasks: dict[str, dict] = {}
        self.goal_progress: list[dict] = []
        self.notifications: list[dict] = []

    def get_environment(self, env_id: str) -> dict | None:
        return self.environments.get(env_id)

    def get_environment_by_chat_id(self, chat_id: int) -> dict | None:
        return self.environments_by_chat.get(chat_id)

    def get_or_create_by_telegram_id(self, telegram_id: int) -> dict:
        return self.users.get(telegram_id, {"id": str(telegram_id), "role": "user", "telegram_id": telegram_id})

    def get_by_telegram_message_id(self, chat_id, message_id):
        return None

    def get_reply_chain(self, msg_id, depth=20):
        return []

    # ── Goals ──

    def create_goal(self, title: str, description: str | None = None, priority: int = 3, deadline=None) -> dict:
        now = datetime.now(UTC)
        goal = {
            "id": str(uuid.uuid4()), "title": title, "description": description,
            "priority": priority, "deadline": deadline, "status": "active",
            "created_at": now, "updated_at": now,
        }
        self.goals[goal["id"]] = goal
        return goal

    def update_goal(self, goal_id: str, **fields) -> dict:
        valid = {"title", "description", "status", "priority", "deadline"}
        unknown = set(fields) - valid
        if unknown:
            raise ValueError(f"Unknown fields: {unknown}")
        goal = self.goals[goal_id]
        goal.update(fields)
        goal["updated_at"] = datetime.now(UTC)
        return goal

    def list_goals(self, status: str | None = None) -> list[dict]:
        goals = list(self.goals.values())
        if status:
            goals = [g for g in goals if g["status"] == status]
        return sorted(goals, key=lambda g: (g["priority"], -g["created_at"].timestamp()))

    def get_goal(self, goal_id: str) -> dict | None:
        return self.goals.get(goal_id)

    # ── Tasks ──

    def create_task(self, title: str, description: str | None = None, goal_id: str | None = None,  # noqa: PLR0913
                    trigger_condition: str | None = None, due_date=None, assigned_to: str = "user") -> dict:
        now = datetime.now(UTC)
        task = {
            "id": str(uuid.uuid4()), "title": title, "description": description,
            "goal_id": goal_id, "trigger_condition": trigger_condition,
            "due_date": due_date, "assigned_to": assigned_to,
            "status": "pending", "result": None, "completed_at": None,
            "created_at": now,
        }
        self.tasks[task["id"]] = task
        return task

    def update_task(self, task_id: str, **fields) -> dict:
        valid = {"title", "description", "status", "goal_id", "trigger_condition", "due_date", "assigned_to", "result"}
        unknown = set(fields) - valid
        if unknown:
            raise ValueError(f"Unknown fields: {unknown}")
        task = self.tasks[task_id]
        if fields.get("status") == "done":
            task["completed_at"] = datetime.now(UTC)
        task.update(fields)
        return task

    def list_tasks(self, goal_id: str | None = None, status: str | None = None, assigned_to: str | None = None) -> list[dict]:
        tasks = list(self.tasks.values())
        if goal_id is not None:
            tasks = [t for t in tasks if t["goal_id"] == goal_id]
        if status is not None:
            tasks = [t for t in tasks if t["status"] == status]
        if assigned_to is not None:
            tasks = [t for t in tasks if t["assigned_to"] == assigned_to]
        return sorted(tasks, key=lambda t: t["created_at"])

    def get_triggered_tasks(self) -> list[dict]:
        return [t for t in self.tasks.values() if t["status"] == "pending" and t["trigger_condition"] is not None]

    def get_due_tasks(self) -> list[dict]:
        now = datetime.now(UTC)
        return [t for t in self.tasks.values() if t["status"] == "pending" and t["due_date"] is not None and t["due_date"] < now]

    # ── Progress ──

    def add_progress(self, goal_id: str, note: str, source: str = "user") -> dict:
        entry = {
            "id": str(uuid.uuid4()), "goal_id": goal_id, "note": note,
            "source": source, "created_at": datetime.now(UTC),
        }
        self.goal_progress.append(entry)
        return entry

    def get_progress(self, goal_id: str, limit: int = 10) -> list[dict]:
        entries = [e for e in self.goal_progress if e["goal_id"] == goal_id]
        return sorted(entries, key=lambda e: e["created_at"], reverse=True)[:limit]

    # ── Summary ──

    def get_active_goals_summary(self) -> str:
        active = [g for g in self.goals.values() if g["status"] == "active"]
        active.sort(key=lambda g: (g["priority"], -g["created_at"].timestamp()))
        lines = []
        for g in active:
            tasks = [t for t in self.tasks.values() if t["goal_id"] == g["id"]]
            done = sum(1 for t in tasks if t["status"] == "done")
            total = len(tasks)
            dl = g["deadline"].strftime("%Y-%m-%d") if g["deadline"] else "нет"
            lines.append(f'Цель [P{g["priority"]}]: "{g["title"]}" (дедлайн: {dl}, задач: {done}/{total})')
        return "\n".join(lines)

    # ── Notifications ──

    def create_notification(self, type: str, payload: dict) -> dict:
        entry = {
            "id": str(uuid.uuid4()), "type": type, "payload": payload,
            "read": False, "created_at": datetime.now(UTC),
        }
        self.notifications.append(entry)
        return entry

    def get_pending_notifications(self) -> list[dict]:
        return [n for n in self.notifications if not n["read"]]

    def mark_notifications_read(self, ids: list[str]) -> None:
        for n in self.notifications:
            if n["id"] in ids:
                n["read"] = True

    def log_run_step(self, run_id, step, type, content):
        self.run_logs.append({"run_id": run_id, "step": step, "type": type, "content": content})

    def get_permissions_for_env(self, env_name: str) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        fallbacks: dict[str, list[str]] = {}
        for (tool, env), roles in self.permissions.items():
            if env == env_name:
                result[tool] = roles
            elif env == "*":
                fallbacks[tool] = roles
        for tool, roles in fallbacks.items():
            if tool not in result:
                result[tool] = roles
        return result

    def grant(self, tool_name: str, environment: str, roles: list[str]) -> None:
        self.permissions[(tool_name, environment)] = roles


# ── Fake Gemini ──────────────────────────────────────────────────────


class FakeGemini:
    """Returns pre-programmed responses. Queue responses with .enqueue()."""

    def __init__(self):
        self._responses: list = []
        self._tool_responses: list = []

    def enqueue(self, response: dict):
        self._responses.append(response)

    def enqueue_tool_response(self, text: str | None, tool_calls: list | None):
        """Queue a response for call_with_tools / continue_with_tool_results."""
        self._tool_responses.append((text, tool_calls))

    def call(self, prompt: str, model: str = "") -> dict:
        if self._responses:
            return self._responses.pop(0)
        return {"reply": "default fake reply"}

    def call_with_tools(self, system_prompt, user_input, declarations, model=""):
        if self._tool_responses:
            text, tool_calls = self._tool_responses.pop(0)
            return text, tool_calls, MagicMock() if tool_calls else None
        return "default reply", None, None

    def continue_with_tool_results(self, history, results, declarations, model="", extra_instruction=None):
        if self._tool_responses:
            text, tool_calls = self._tool_responses.pop(0)
            return text, tool_calls, MagicMock() if tool_calls else None
        return "continued reply", None, None


# ── Fake Retriever ───────────────────────────────────────────────────


class FakeRetriever:
    def get_user_context(self, user_id: str) -> str:
        return ""

    def get_core(self) -> str:
        return ""

    def get_context(self, *, role="admin", user_id=None, environment=None) -> str:
        return ""

    def get_domain_context(self, domain: str) -> str:
        return ""

    def retrieve(self, query: str, *, role="admin", user_id=None,
                 environment=None, domain=None, **kwargs) -> str:
        return ""


# ── Test Tools ───────────────────────────────────────────────────────


def make_tool(name: str, *, nl_routable=True, conversational=False,
              permissions=None, fn=None) -> Tool:
    return Tool(
        name=name,
        description=f"Test tool: {name}",
        parameters={"type": "object", "properties": {"input": {"type": "string"}}},
        fn=fn or (lambda args, ctx: {"result": f"{name} called", "input": args.get("input")}),
        permissions=permissions or {"*": {"admin", "user"}},
        nl_routable=nl_routable,
        conversational=conversational,
    )


@pytest.fixture(autouse=True)
def _clean_tool_registry():
    """Save and restore the global TOOLS registry around each test."""
    saved = dict(TOOLS)
    yield
    TOOLS.clear()
    TOOLS.update(saved)


@pytest.fixture
def fake_db():
    return FakeDb()


@pytest.fixture
def fake_gemini():
    return FakeGemini()


@pytest.fixture
def fake_retriever():
    return FakeRetriever()
