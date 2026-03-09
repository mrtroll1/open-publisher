"""Tool permission repository — DB-driven access control."""

from __future__ import annotations

from backend.infrastructure.repositories.postgres.base import BasePostgresRepo


class PermissionRepo(BasePostgresRepo):

    def get_permissions_for_env(self, env_name: str) -> dict[str, list[str]]:
        """Return {tool_name: [roles]} for a specific environment + fallback '*'."""
        with self._cursor() as cur:
            cur.execute(
                """SELECT tool_name, environment, allowed_roles
                   FROM tool_permissions
                   WHERE environment IN (%s, '*')
                   ORDER BY tool_name""",
                (env_name,),
            )
            result: dict[str, list[str]] = {}
            fallbacks: dict[str, list[str]] = {}
            for tool_name, environment, roles in cur.fetchall():
                if environment == env_name:
                    result[tool_name] = roles
                else:
                    fallbacks[tool_name] = roles
            # Use env-specific if present, otherwise fallback to '*'
            for tool_name, roles in fallbacks.items():
                if tool_name not in result:
                    result[tool_name] = roles
            return result

    def list_permissions(self) -> list[dict]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT tool_name, environment, allowed_roles FROM tool_permissions ORDER BY tool_name, environment"
            )
            return [
                {"tool_name": r[0], "environment": r[1], "allowed_roles": r[2]}
                for r in cur.fetchall()
            ]

    def grant(self, tool_name: str, environment: str, roles: list[str]) -> None:
        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO tool_permissions (tool_name, environment, allowed_roles)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (tool_name, environment)
                   DO UPDATE SET allowed_roles = EXCLUDED.allowed_roles""",
                (tool_name, environment, roles),
            )

    def revoke(self, tool_name: str, environment: str) -> bool:
        with self._cursor() as cur:
            cur.execute(
                "DELETE FROM tool_permissions WHERE tool_name = %s AND environment = %s",
                (tool_name, environment),
            )
            return cur.rowcount > 0
