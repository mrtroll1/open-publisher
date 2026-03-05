"""Conversation history repository."""

from __future__ import annotations

import json

from backend.infrastructure.repositories.postgres.base import BasePostgresRepo


class ConversationRepo(BasePostgresRepo):

    def save_conversation(self, chat_id: int, user_id: int, role: str, content: str,
                          reply_to_id: str | None = None, message_id: int | None = None,
                          metadata: dict | None = None) -> str:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO conversations
                   (chat_id, user_id, role, content, reply_to_id, message_id, metadata)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (chat_id, user_id, role, content, reply_to_id, message_id,
                 json.dumps(metadata or {})),
            )
            return str(cur.fetchone()[0])

    def get_conversation_by_message_id(self, chat_id: int, message_id: int) -> dict | None:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM conversations WHERE chat_id = %s AND message_id = %s",
                (chat_id, message_id),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [desc[0] for desc in cur.description]
            result = dict(zip(cols, row))
            result["id"] = str(result["id"])
            if result.get("reply_to_id"):
                result["reply_to_id"] = str(result["reply_to_id"])
            return result

    def get_recent_conversations(self, chat_id: int, hours: int = 24) -> list[dict]:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """SELECT role, content, created_at
                   FROM conversations
                   WHERE chat_id = %s AND created_at >= NOW() - %s * INTERVAL '1 hour'
                   ORDER BY created_at""",
                (chat_id, hours),
            )
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get_unextracted_conversations(self, chat_id: int) -> list[dict]:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, role, content, created_at
                   FROM conversations
                   WHERE chat_id = %s AND knowledge_extracted_at IS NULL
                   ORDER BY created_at""",
                (chat_id,),
            )
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def mark_conversations_extracted(self, conversation_ids: list[str]) -> None:
        if not conversation_ids:
            return
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE conversations
                   SET knowledge_extracted_at = NOW()
                   WHERE id = ANY(%s::uuid[])""",
                (conversation_ids,),
            )
            conn.commit()

    def get_reply_chain(self, conversation_id: str, depth: int = 20) -> list[dict]:
        conn = self._get_conn()
        chain: list[dict] = []
        current_id = conversation_id
        with conn.cursor() as cur:
            for _ in range(depth):
                cur.execute("SELECT * FROM conversations WHERE id = %s", (current_id,))
                row = cur.fetchone()
                if not row:
                    break
                cols = [desc[0] for desc in cur.description]
                rec = dict(zip(cols, row))
                rec["id"] = str(rec["id"])
                if rec.get("reply_to_id"):
                    rec["reply_to_id"] = str(rec["reply_to_id"])
                chain.append(rec)
                if not rec.get("reply_to_id"):
                    break
                current_id = rec["reply_to_id"]
        chain.reverse()
        return chain
