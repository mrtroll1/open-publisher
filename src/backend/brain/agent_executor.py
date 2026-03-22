"""Agent task executor — runs agent tasks through the full ReAct loop with tools."""

from __future__ import annotations

import logging

from backend.brain.authorizer import AuthContext
from backend.brain.tool import TOOLS, ToolContext

logger = logging.getLogger(__name__)

# Tools available to autonomous agent tasks
_AGENT_TOOLS = {"web_search", "web_scrape", "search", "republic_db", "agent_db", "teach", "code"}


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
            user={"role": "admin"},
        )
        return AuthContext(ctx=ctx, tools=tools, env_name="agent_task", role="admin")
