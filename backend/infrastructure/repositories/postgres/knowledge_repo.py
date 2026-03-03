"""Knowledge entries repository."""

from __future__ import annotations

from backend.infrastructure.repositories.postgres.base import BasePostgresRepo


class KnowledgeRepo(BasePostgresRepo):

    def save_knowledge_entry(self, tier: str, scope: str, title: str, content: str, source: str, embedding: list[float] | None = None) -> str:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO knowledge_entries (tier, scope, title, content, source, embedding)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (tier, scope, title, content, source, str(embedding) if embedding is not None else None),
            )
            return str(cur.fetchone()[0])

    def update_knowledge_entry(self, entry_id: str, content: str, embedding: list[float] | None = None) -> bool:
        """Update a knowledge entry. Returns True if an entry was actually updated."""
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE knowledge_entries
                   SET content = %s, embedding = %s, updated_at = NOW()
                   WHERE id = %s""",
                (content, str(embedding) if embedding is not None else None, entry_id),
            )
            return cur.rowcount > 0

    def search_knowledge(self, query_embedding: list[float], scope: str | None = None, limit: int = 5) -> list[dict]:
        conn = self._get_conn()
        emb_str = str(query_embedding)
        with conn.cursor() as cur:
            if scope is not None:
                cur.execute(
                    """SELECT id, tier, scope, title, content, source,
                              1 - (embedding <=> %s::vector) AS similarity
                       FROM knowledge_entries
                       WHERE is_active = TRUE AND scope = %s
                       ORDER BY embedding <=> %s::vector ASC
                       LIMIT %s""",
                    (emb_str, scope, emb_str, limit),
                )
            else:
                cur.execute(
                    """SELECT id, tier, scope, title, content, source,
                              1 - (embedding <=> %s::vector) AS similarity
                       FROM knowledge_entries
                       WHERE is_active = TRUE
                       ORDER BY embedding <=> %s::vector ASC
                       LIMIT %s""",
                    (emb_str, emb_str, limit),
                )
            cols = ["id", "tier", "scope", "title", "content", "source", "similarity"]
            rows = []
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                d["id"] = str(d["id"])
                rows.append(d)
            return rows

    def get_knowledge_by_tier(self, tier: str) -> list[dict]:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, tier, scope, title, content, source
                   FROM knowledge_entries
                   WHERE tier = %s AND is_active = TRUE
                   ORDER BY scope, created_at""",
                (tier,),
            )
            cols = ["id", "tier", "scope", "title", "content", "source"]
            rows = []
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                d["id"] = str(d["id"])
                rows.append(d)
            return rows

    def get_knowledge_by_scope(self, scope: str) -> list[dict]:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, tier, scope, title, content, source
                   FROM knowledge_entries
                   WHERE scope = %s AND is_active = TRUE
                   ORDER BY created_at""",
                (scope,),
            )
            cols = ["id", "tier", "scope", "title", "content", "source"]
            rows = []
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                d["id"] = str(d["id"])
                rows.append(d)
            return rows

    def list_knowledge(self, scope: str | None = None, tier: str | None = None) -> list[dict]:
        conn = self._get_conn()
        with conn.cursor() as cur:
            sql = """SELECT id, tier, scope, title, content, source, created_at
                     FROM knowledge_entries
                     WHERE is_active = TRUE"""
            params: list = []
            if scope is not None:
                sql += " AND scope = %s"
                params.append(scope)
            if tier is not None:
                sql += " AND tier = %s"
                params.append(tier)
            sql += " ORDER BY tier, scope, created_at"
            cur.execute(sql, tuple(params))
            cols = ["id", "tier", "scope", "title", "content", "source", "created_at"]
            rows = []
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                d["id"] = str(d["id"])
                rows.append(d)
            return rows

    def deactivate_knowledge(self, entry_id: str) -> bool:
        """Soft-delete a knowledge entry. Returns True if an entry was actually deactivated."""
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE knowledge_entries SET is_active = FALSE, updated_at = NOW() WHERE id = %s",
                (entry_id,),
            )
            return cur.rowcount > 0
