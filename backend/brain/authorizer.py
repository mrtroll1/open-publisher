from __future__ import annotations

from dataclasses import dataclass

from common.config import ADMIN_TELEGRAM_IDS
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
        role = self._resolve_role(user_id)
        routes = self._filter_routes(role)
        return AuthContext(env=env, user=user, routes=routes)

    def _resolve_env(self, environment_id: str) -> dict:
        # Try by name first, then by chat_id if numeric
        result = self._db.get_environment(environment_id)
        if not result and environment_id.lstrip("-").isdigit():
            result = self._db.get_environment_by_chat_id(int(environment_id))
        return result or {}

    def _resolve_user(self, user_id: str) -> dict:
        if not user_id:
            return {}
        result = self._db.find_entity_by_external_id("telegram_user_id", user_id)
        return result or {}

    def _resolve_role(self, user_id: str) -> str:
        if user_id and user_id.lstrip("-").isdigit() and int(user_id) in ADMIN_TELEGRAM_IDS:
            return "admin"
        return "user"

    def _filter_routes(self, role: str) -> list[Route]:
        if role == "admin":
            return list(ROUTES.values())
        return [r for r in ROUTES.values() if role in r.permissions or "public" in r.permissions]
