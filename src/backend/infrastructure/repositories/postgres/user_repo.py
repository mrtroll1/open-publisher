"""User repository."""

from __future__ import annotations

from backend.infrastructure.repositories.postgres.base import BasePostgresRepo

_USER_COLS = ["id", "name", "role", "telegram_id", "email", "created_at", "updated_at"]


def _user_row(row) -> dict:
    d = dict(zip(_USER_COLS, row, strict=False))
    d["id"] = str(d["id"])
    return d


class UserRepo(BasePostgresRepo):

    def save_user(self, name: str, role: str = "user",
                  telegram_id: int | None = None,
                  email: str | None = None) -> str:
        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO users (name, role, telegram_id, email)
                   VALUES (%s, %s, %s, %s)
                   RETURNING id""",
                (name, role, telegram_id, email),
            )
            return str(cur.fetchone()[0])

    def get_user(self, user_id: str) -> dict | None:
        with self._cursor() as cur:
            cur.execute(f"SELECT {', '.join(_USER_COLS)} FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            return _user_row(row) if row else None

    def get_user_by_telegram_id(self, telegram_id: int) -> dict | None:
        with self._cursor() as cur:
            cur.execute(f"SELECT {', '.join(_USER_COLS)} FROM users WHERE telegram_id = %s", (telegram_id,))
            row = cur.fetchone()
            return _user_row(row) if row else None

    def get_user_by_email(self, email: str) -> dict | None:
        with self._cursor() as cur:
            cur.execute(f"SELECT {', '.join(_USER_COLS)} FROM users WHERE email = %s", (email,))
            row = cur.fetchone()
            return _user_row(row) if row else None

    def get_or_create_by_email(self, email: str) -> dict:
        existing = self.get_user_by_email(email)
        if existing:
            return existing
        user_id = self.save_user(name=email.split("@", maxsplit=1)[0], email=email)
        return self.get_user(user_id)

    def get_or_create_by_telegram_id(self, telegram_id: int) -> dict:
        existing = self.get_user_by_telegram_id(telegram_id)
        if existing:
            return existing
        user_id = self.save_user(name="", telegram_id=telegram_id)
        return self.get_user(user_id)

    def update_user(self, user_id: str, **fields) -> bool:
        allowed = {"name", "role", "telegram_id", "email"}
        to_update = {k: v for k, v in fields.items() if k in allowed}
        if not to_update:
            return False
        set_parts = [f"{col} = %s" for col in to_update]
        set_parts.append("updated_at = NOW()")
        params = [*list(to_update.values()), user_id]
        sql = f"UPDATE users SET {', '.join(set_parts)} WHERE id = %s"
        with self._cursor() as cur:
            cur.execute(sql, tuple(params))
            return cur.rowcount > 0

    def get_admin_telegram_ids(self) -> list[int]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT telegram_id FROM users WHERE role = 'admin' AND telegram_id IS NOT NULL",
            )
            return [row[0] for row in cur.fetchall()]

    def get_user_knowledge(self, user_id: str, limit: int = 10) -> list[dict]:
        with self._cursor() as cur:
            cur.execute(
                """SELECT id, tier, domain, title, content, source, created_at
                   FROM unit_of_knowledge
                   WHERE user_id = %s AND is_active = TRUE
                   ORDER BY created_at DESC
                   LIMIT %s""",
                (user_id, limit),
            )
            cols = ["id", "tier", "domain", "title", "content", "source", "created_at"]
            rows = []
            for row in cur.fetchall():
                d = dict(zip(cols, row, strict=False))
                d["id"] = str(d["id"])
                rows.append(d)
            return rows
