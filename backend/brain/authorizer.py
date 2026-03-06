from __future__ import annotations

from dataclasses import dataclass

from backend.brain.routes import Route, ROUTES
from backend.infrastructure.repositories.postgres import DbGateway


@dataclass
class AuthContext:
    env: dict
    user: dict
    routes: list[Route]


class Authorizer:
    def __init__(self, db: DbGateway):
        self._db = db

    def authorize(self, environment_id: str, user_id: str) -> AuthContext:
        env = self._resolve_env(environment_id)
        user = self._resolve_user(user_id)
        role = user.get("role", "user")
        env_name = env.get("name", "")
        routes = self._filter_routes(role, env_name)
        return AuthContext(env=env, user=user, routes=routes)

    def _resolve_env(self, environment_id: str) -> dict:
        result = self._db.get_environment(environment_id)
        if not result and environment_id.lstrip("-").isdigit():
            result = self._db.get_environment_by_chat_id(int(environment_id))
        return result or {}

    def _resolve_user(self, user_id: str) -> dict:
        if not user_id:
            return {}
        if user_id.lstrip("-").isdigit():
            result = self._db.get_user_by_telegram_id(int(user_id))
            if result:
                return result
        return {}

    def _filter_routes(self, role: str, env_name: str) -> list[Route]:
        result = []
        for route in ROUTES.values():
            allowed = route.permissions.get(env_name) or route.permissions.get("*", set())
            if role in allowed:
                result.append(route)
        return result
