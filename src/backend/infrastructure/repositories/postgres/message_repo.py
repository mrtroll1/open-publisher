"""Unified message repository — all conversations, emails, and system messages."""

from __future__ import annotations

import json
import re

from backend.infrastructure.repositories.postgres.base import BasePostgresRepo

_RE_PREFIX = re.compile(r"^(Re|Fwd|Fw)\s*:\s*", re.IGNORECASE)

_MSG_COLS = ["id", "text", "environment", "chat_id", "type", "user_id",
             "parent_id", "created_at", "metadata"]


def normalize_email_subject(subject: str) -> str:
    s = subject.strip()
    while _RE_PREFIX.match(s):
        s = _RE_PREFIX.sub("", s, count=1).strip()
    return s.lower()


def _row_to_dict(row, cols=_MSG_COLS) -> dict:
    d = dict(zip(cols, row))
    d["id"] = str(d["id"])
    if d.get("parent_id"):
        d["parent_id"] = str(d["parent_id"])
    if d.get("user_id"):
        d["user_id"] = str(d["user_id"])
    return d


class MessageRepo(BasePostgresRepo):

    def save_message(self, text: str, environment: str | None = None,
                     chat_id: int | None = None, type: str = "user",
                     user_id: str | None = None, parent_id: str | None = None,
                     metadata: dict | None = None, embedding: list[float] | None = None) -> str:
        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO messages (text, environment, chat_id, type, user_id,
                              parent_id, metadata, embedding)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (text, environment, chat_id, type, user_id, parent_id,
                 json.dumps(metadata or {}),
                 str(embedding) if embedding is not None else None),
            )
            return str(cur.fetchone()[0])

    def get_message(self, message_id: str) -> dict | None:
        with self._cursor() as cur:
            cur.execute(
                f"SELECT {', '.join(_MSG_COLS)} FROM messages WHERE id = %s",
                (message_id,),
            )
            row = cur.fetchone()
            return _row_to_dict(row) if row else None

    def get_by_telegram_message_id(self, chat_id: int, telegram_message_id: int) -> dict | None:
        with self._cursor() as cur:
            cur.execute(
                f"""SELECT {', '.join(_MSG_COLS)} FROM messages
                    WHERE chat_id = %s AND metadata->>'telegram_message_id' = %s""",
                (chat_id, str(telegram_message_id)),
            )
            row = cur.fetchone()
            return _row_to_dict(row) if row else None

    def get_reply_chain(self, message_id: str, depth: int = 20) -> list[dict]:
        chain: list[dict] = []
        current_id = message_id
        with self._cursor() as cur:
            for _ in range(depth):
                cur.execute(
                    f"SELECT {', '.join(_MSG_COLS)} FROM messages WHERE id = %s",
                    (current_id,),
                )
                row = cur.fetchone()
                if not row:
                    break
                rec = _row_to_dict(row)
                chain.append(rec)
                if not rec.get("parent_id"):
                    break
                current_id = rec["parent_id"]
        chain.reverse()
        return chain

    def get_recent(self, chat_id: int, hours: int = 24) -> list[dict]:
        with self._cursor() as cur:
            cur.execute(
                f"""SELECT {', '.join(_MSG_COLS)} FROM messages
                    WHERE chat_id = %s AND created_at >= NOW() - %s * INTERVAL '1 hour'
                    ORDER BY created_at""",
                (chat_id, hours),
            )
            return [_row_to_dict(row) for row in cur.fetchall()]

    def update_metadata(self, message_id: str, updates: dict) -> bool:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE messages SET metadata = metadata || %s WHERE id = %s",
                (json.dumps(updates), message_id),
            )
            return cur.rowcount > 0

    # --- Email-specific helpers ---

    def find_email_parent(self, in_reply_to: str | None = None,
                          subject: str | None = None) -> str | None:
        """Find parent message for an email thread by in_reply_to or normalized subject."""
        with self._cursor() as cur:
            if in_reply_to:
                cur.execute(
                    "SELECT id FROM messages WHERE metadata->>'email_message_id' = %s",
                    (in_reply_to,),
                )
                row = cur.fetchone()
                if row:
                    return str(row[0])
            if subject:
                normalized = normalize_email_subject(subject)
                if normalized:
                    cur.execute(
                        """SELECT id FROM messages
                           WHERE metadata->>'normalized_subject' = %s
                           ORDER BY created_at DESC LIMIT 1""",
                        (normalized,),
                    )
                    row = cur.fetchone()
                    if row:
                        return str(row[0])
        return None

    def get_thread_history(self, message_id: str, limit: int = 10) -> list[dict]:
        """Get all messages in a thread by walking up to root, then fetching all descendants."""
        # Walk up to find root
        root_id = message_id
        with self._cursor() as cur:
            for _ in range(50):
                cur.execute("SELECT parent_id FROM messages WHERE id = %s", (root_id,))
                row = cur.fetchone()
                if not row or not row[0]:
                    break
                root_id = str(row[0])

            # Get all messages in thread via recursive CTE
            cur.execute(
                f"""WITH RECURSIVE thread AS (
                        SELECT {', '.join(_MSG_COLS)} FROM messages WHERE id = %s
                        UNION ALL
                        SELECT {', '.join('m.' + c for c in _MSG_COLS)}
                        FROM messages m JOIN thread t ON m.parent_id = t.id
                    )
                    SELECT {', '.join(_MSG_COLS)} FROM thread
                    ORDER BY created_at LIMIT %s""",
                (root_id, limit),
            )
            return [_row_to_dict(row) for row in cur.fetchall()]
