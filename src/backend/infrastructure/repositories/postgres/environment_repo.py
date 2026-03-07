"""Environment and chat binding repository."""

from __future__ import annotations

from backend.infrastructure.repositories.postgres.base import BasePostgresRepo


class EnvironmentRepo(BasePostgresRepo):

    def get_environment(self, name: str) -> dict | None:
        with self._cursor() as cur:
            cur.execute(
                """SELECT name, description, system_context, allowed_domains,
                          created_at, updated_at
                   FROM environments WHERE name = %s""",
                (name,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = ["name", "description", "system_context", "allowed_domains",
                    "created_at", "updated_at"]
            return dict(zip(cols, row, strict=False))

    def get_environment_by_chat_id(self, chat_id: int) -> dict | None:
        with self._cursor() as cur:
            cur.execute(
                """SELECT e.name, e.description, e.system_context, e.allowed_domains,
                          e.created_at, e.updated_at
                   FROM environment_bindings b
                   JOIN environments e ON e.name = b.environment
                   WHERE b.chat_id = %s""",
                (chat_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = ["name", "description", "system_context", "allowed_domains",
                    "created_at", "updated_at"]
            return dict(zip(cols, row, strict=False))

    def list_environments(self) -> list[dict]:
        with self._cursor() as cur:
            cur.execute(
                """SELECT name, description, system_context, allowed_domains,
                          created_at, updated_at
                   FROM environments ORDER BY name"""
            )
            cols = ["name", "description", "system_context", "allowed_domains",
                    "created_at", "updated_at"]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def save_environment(self, name: str, description: str, system_context: str,
                         allowed_domains: list[str] | None = None) -> str:
        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO environments (name, description, system_context, allowed_domains)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (name) DO UPDATE
                   SET description = EXCLUDED.description,
                       system_context = EXCLUDED.system_context,
                       allowed_domains = EXCLUDED.allowed_domains,
                       updated_at = NOW()""",
                (name, description, system_context, allowed_domains),
            )
            return name

    def update_environment(self, name: str, **fields) -> bool:
        allowed = {"description", "system_context", "allowed_domains"}
        to_update = {k: v for k, v in fields.items() if k in allowed}
        if not to_update:
            return False
        set_parts = [f"{col} = %s" for col in to_update]
        set_parts.append("updated_at = NOW()")
        sql = f"UPDATE environments SET {', '.join(set_parts)} WHERE name = %s"
        params = [*list(to_update.values()), name]
        with self._cursor() as cur:
            cur.execute(sql, tuple(params))
            return cur.rowcount > 0

    def get_bindings_for_environment(self, environment: str) -> list[int]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT chat_id FROM environment_bindings WHERE environment = %s ORDER BY chat_id",
                (environment,),
            )
            return [row[0] for row in cur.fetchall()]

    def bind_chat(self, chat_id: int, environment: str) -> None:
        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO environment_bindings (chat_id, environment)
                   VALUES (%s, %s)
                   ON CONFLICT (chat_id) DO UPDATE
                   SET environment = EXCLUDED.environment""",
                (chat_id, environment),
            )

    def unbind_chat(self, chat_id: int) -> None:
        with self._cursor() as cur:
            cur.execute(
                "DELETE FROM environment_bindings WHERE chat_id = %s",
                (chat_id,),
            )
