"""Environment and chat binding repository."""

from __future__ import annotations

import typing

from backend.infrastructure.repositories.postgres.base import BasePostgresRepo


class EnvironmentRepo(BasePostgresRepo):

    _ENV_COLS: typing.ClassVar = ["name", "description", "system_context", "allowed_domains",
                                  "created_at", "updated_at", "last_summarized_at", "telegram_handle"]
    _ENV_SELECT = """SELECT name, description, system_context, allowed_domains,
                            created_at, updated_at, last_summarized_at, telegram_handle
                     FROM environments"""

    def get_environment(self, name: str) -> dict | None:
        with self._cursor() as cur:
            cur.execute(f"{self._ENV_SELECT} WHERE name = %s", (name,))
            row = cur.fetchone()
            if not row:
                return None
            return dict(zip(self._ENV_COLS, row, strict=False))

    def get_environment_by_chat_id(self, chat_id: int) -> dict | None:
        with self._cursor() as cur:
            cur.execute(
                """SELECT e.name, e.description, e.system_context, e.allowed_domains,
                          e.created_at, e.updated_at, e.last_summarized_at, e.telegram_handle
                   FROM environment_bindings b
                   JOIN environments e ON e.name = b.environment
                   WHERE b.chat_id = %s""",
                (chat_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return dict(zip(self._ENV_COLS, row, strict=False))

    def list_environments(self) -> list[dict]:
        with self._cursor() as cur:
            cur.execute(f"{self._ENV_SELECT} ORDER BY name")
            return [dict(zip(self._ENV_COLS, row, strict=False)) for row in cur.fetchall()]

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
        allowed = {"description", "system_context", "allowed_domains",
                   "last_summarized_at", "telegram_handle"}
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

    def list_scrapable_environments(self) -> list[dict]:
        with self._cursor() as cur:
            cur.execute(
                f"{self._ENV_SELECT} WHERE telegram_handle IS NOT NULL ORDER BY name"
            )
            return [dict(zip(self._ENV_COLS, row, strict=False)) for row in cur.fetchall()]

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
