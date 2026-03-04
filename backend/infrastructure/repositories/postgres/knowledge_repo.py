"""Knowledge entries repository."""

from __future__ import annotations

from backend.infrastructure.repositories.postgres.base import BasePostgresRepo


class KnowledgeRepo(BasePostgresRepo):

    def save_knowledge_entry(self, tier: str, domain: str, title: str, content: str, source: str, embedding: list[float] | None = None) -> str:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO knowledge_entries (tier, domain, title, content, source, embedding)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (tier, domain, title, content, source, str(embedding) if embedding is not None else None),
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

    def search_knowledge(self, query_embedding: list[float], domain: str | None = None, limit: int = 5) -> list[dict]:
        conn = self._get_conn()
        emb_str = str(query_embedding)
        with conn.cursor() as cur:
            if domain is not None:
                cur.execute(
                    """SELECT id, tier, domain, title, content, source,
                              1 - (embedding <=> %s::vector) AS similarity
                       FROM knowledge_entries
                       WHERE is_active = TRUE AND domain = %s
                       ORDER BY embedding <=> %s::vector ASC
                       LIMIT %s""",
                    (emb_str, domain, emb_str, limit),
                )
            else:
                cur.execute(
                    """SELECT id, tier, domain, title, content, source,
                              1 - (embedding <=> %s::vector) AS similarity
                       FROM knowledge_entries
                       WHERE is_active = TRUE
                       ORDER BY embedding <=> %s::vector ASC
                       LIMIT %s""",
                    (emb_str, emb_str, limit),
                )
            cols = ["id", "tier", "domain", "title", "content", "source", "similarity"]
            rows = []
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                d["id"] = str(d["id"])
                rows.append(d)
            return rows

    def search_knowledge_multi_domain(
        self, query_embedding: list[float],
        domains: list[str] | None = None,
        limit: int = 5,
    ) -> list[dict]:
        conn = self._get_conn()
        emb_str = str(query_embedding)
        with conn.cursor() as cur:
            if domains is not None:
                cur.execute(
                    """SELECT id, tier, domain, title, content, source,
                              1 - (embedding <=> %s::vector) AS similarity
                       FROM knowledge_entries
                       WHERE is_active = TRUE AND domain = ANY(%s)
                       ORDER BY embedding <=> %s::vector ASC
                       LIMIT %s""",
                    (emb_str, domains, emb_str, limit),
                )
            else:
                cur.execute(
                    """SELECT id, tier, domain, title, content, source,
                              1 - (embedding <=> %s::vector) AS similarity
                       FROM knowledge_entries
                       WHERE is_active = TRUE
                       ORDER BY embedding <=> %s::vector ASC
                       LIMIT %s""",
                    (emb_str, emb_str, limit),
                )
            cols = ["id", "tier", "domain", "title", "content", "source", "similarity"]
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
                """SELECT id, tier, domain, title, content, source
                   FROM knowledge_entries
                   WHERE tier = %s AND is_active = TRUE
                   ORDER BY domain, created_at""",
                (tier,),
            )
            cols = ["id", "tier", "domain", "title", "content", "source"]
            rows = []
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                d["id"] = str(d["id"])
                rows.append(d)
            return rows

    def get_domain_context(self, domain: str) -> list[dict]:
        """Fetch core (global) + meta (domain-wide) entries for a domain."""
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, tier, domain, title, content, source
                   FROM knowledge_entries
                   WHERE is_active = TRUE
                     AND (tier = 'core' OR (tier = 'meta' AND domain = %s))
                   ORDER BY tier, created_at""",
                (domain,),
            )
            cols = ["id", "tier", "domain", "title", "content", "source"]
            rows = []
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                d["id"] = str(d["id"])
                rows.append(d)
            return rows

    def get_multi_domain_context(self, domains: list[str]) -> list[dict]:
        """Fetch core (global) + meta entries for multiple domains."""
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, tier, domain, title, content, source
                   FROM knowledge_entries
                   WHERE is_active = TRUE
                     AND (tier = 'core' OR (tier = 'meta' AND domain = ANY(%s)))
                   ORDER BY tier, created_at""",
                (domains,),
            )
            cols = ["id", "tier", "domain", "title", "content", "source"]
            rows = []
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                d["id"] = str(d["id"])
                rows.append(d)
            return rows

    def get_knowledge_by_domain(self, domain: str) -> list[dict]:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, tier, domain, title, content, source
                   FROM knowledge_entries
                   WHERE domain = %s AND is_active = TRUE
                   ORDER BY created_at""",
                (domain,),
            )
            cols = ["id", "tier", "domain", "title", "content", "source"]
            rows = []
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                d["id"] = str(d["id"])
                rows.append(d)
            return rows

    def list_knowledge(self, domain: str | None = None, tier: str | None = None) -> list[dict]:
        conn = self._get_conn()
        with conn.cursor() as cur:
            sql = """SELECT id, tier, domain, title, content, source, created_at
                     FROM knowledge_entries
                     WHERE is_active = TRUE"""
            params: list = []
            if domain is not None:
                sql += " AND domain = %s"
                params.append(domain)
            if tier is not None:
                sql += " AND tier = %s"
                params.append(tier)
            sql += " ORDER BY tier, domain, created_at"
            cur.execute(sql, tuple(params))
            cols = ["id", "tier", "domain", "title", "content", "source", "created_at"]
            rows = []
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                d["id"] = str(d["id"])
                rows.append(d)
            return rows

    def get_knowledge_entry(self, entry_id: str) -> dict | None:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, tier, domain, title, content, source, created_at
                   FROM knowledge_entries
                   WHERE id = %s AND is_active = TRUE""",
                (entry_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = ["id", "tier", "domain", "title", "content", "source", "created_at"]
            d = dict(zip(cols, row))
            d["id"] = str(d["id"])
            return d

    def deactivate_knowledge(self, entry_id: str) -> bool:
        """Soft-delete a knowledge entry. Returns True if an entry was actually deactivated."""
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE knowledge_entries SET is_active = FALSE, updated_at = NOW() WHERE id = %s",
                (entry_id,),
            )
            return cur.rowcount > 0

    # ── Knowledge domains ────────────────────────────────────────────

    def list_domains(self) -> list[dict]:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT name, description FROM knowledge_domains ORDER BY name")
            return [{"name": row[0], "description": row[1]} for row in cur.fetchall()]

    def get_or_create_domain(self, name: str, description: str = "") -> str:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO knowledge_domains (name, description) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING",
                (name, description),
            )
            return name
