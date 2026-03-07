from __future__ import annotations

from dataclasses import dataclass

from backend.brain.tool import TOOLS, Tool, ToolContext
from backend.infrastructure.repositories.postgres import DbGateway


@dataclass
class AuthContext:
    ctx: ToolContext
    tools: list[Tool]
    env_name: str
    role: str


class Authorizer:
    def __init__(self, db: DbGateway):
        self._db = db

    def authorize(self, environment_id: str, user_id: str) -> AuthContext:
        env = self._resolve_env(environment_id)
        user = self._resolve_user(user_id)
        role = user.get("role", "user")
        env_name = env.get("name", "")
        tools = self._filter_tools(role, env_name)
        ctx = ToolContext(env=env, user=user)
        return AuthContext(ctx=ctx, tools=tools, env_name=env_name, role=role)

    def _resolve_env(self, environment_id: str) -> dict:
        result = self._db.get_environment(environment_id)
        if not result and environment_id.lstrip("-").isdigit():
            result = self._db.get_environment_by_chat_id(int(environment_id))
        return result or {}

    def _resolve_user(self, user_id: str) -> dict:
        if not user_id:
            return {}
        if user_id.lstrip("-").isdigit():
            return self._db.get_or_create_by_telegram_id(int(user_id))
        return {}

    def _filter_tools(self, role: str, env_name: str) -> list[Tool]:
        result = []
        for tool in TOOLS.values():
            allowed = tool.permissions.get(env_name) or tool.permissions.get("*", set())
            if "*" in allowed or role in allowed:
                result.append(tool)
        return result
