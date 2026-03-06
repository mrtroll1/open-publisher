"""User repository."""

from __future__ import annotations

from backend.infrastructure.repositories.postgres.base import BasePostgresRepo


class UserRepo(BasePostgresRepo):

    def save_user(self, name: str, role: str = "user",
                  telegram_id: int | None = None) -> str:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO users (name, role, telegram_id)
                   VALUES (%s, %s, %s)
                   RETURNING id""",
                (name, role, telegram_id),
            )
            return str(cur.fetchone()[0])

    def get_user(self, user_id: str) -> dict | None:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, role, telegram_id, created_at, updated_at FROM users WHERE id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = ["id", "name", "role", "telegram_id", "created_at", "updated_at"]
            d = dict(zip(cols, row))
            d["id"] = str(d["id"])
            return d

    def get_user_by_telegram_id(self, telegram_id: int) -> dict | None:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, role, telegram_id, created_at, updated_at FROM users WHERE telegram_id = %s",
                (telegram_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = ["id", "name", "role", "telegram_id", "created_at", "updated_at"]
            d = dict(zip(cols, row))
            d["id"] = str(d["id"])
            return d

    def update_user(self, user_id: str, **fields) -> bool:
        allowed = {"name", "role", "telegram_id"}
        to_update = {k: v for k, v in fields.items() if k in allowed}
        if not to_update:
            return False
        set_parts = [f"{col} = %s" for col in to_update]
        set_parts.append("updated_at = NOW()")
        params = list(to_update.values()) + [user_id]
        sql = f"UPDATE users SET {', '.join(set_parts)} WHERE id = %s"
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            return cur.rowcount > 0

    def get_admin_telegram_ids(self) -> list[int]:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT telegram_id FROM users WHERE role = 'admin' AND telegram_id IS NOT NULL",
            )
            return [row[0] for row in cur.fetchall()]

    def get_user_knowledge(self, user_id: str, limit: int = 10) -> list[dict]:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, tier, domain, title, content, source, created_at
                   FROM knowledge_entries
                   WHERE user_id = %s AND is_active = TRUE
                   ORDER BY created_at DESC
                   LIMIT %s""",
                (user_id, limit),
            )
            cols = ["id", "tier", "domain", "title", "content", "source", "created_at"]
            rows = []
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                d["id"] = str(d["id"])
                rows.append(d)
            return rows
