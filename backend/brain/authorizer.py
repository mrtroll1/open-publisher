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
        routes = self._filter_routes(env, user)
        return AuthContext(env=env, user=user, routes=routes)

    def _resolve_env(self, environment_id: str) -> dict:
        # Try by name first, then by chat_id if numeric
        result = self._db.get_environment(environment_id)
        if not result and environment_id.lstrip("-").isdigit():
            result = self._db.get_environment_by_chat_id(int(environment_id))
        return result or {}

    def _resolve_user(self, user_id: str) -> dict:
        result = self._db.find_entity_by_external_id("telegram_user_id", user_id)
        return result or {}

    def _filter_routes(self, env: dict, user: dict) -> list[Route]:
        if user:
            return list(ROUTES.values())
        return [r for r in ROUTES.values() if "public" in r.permissions]
