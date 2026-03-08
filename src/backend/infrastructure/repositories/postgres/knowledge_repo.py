"""Knowledge entries repository."""

from __future__ import annotations

from backend.infrastructure.repositories.postgres.base import BasePostgresRepo

_ENTRY_COLS = ("id", "tier", "domain", "title", "content", "source")
_ENTRY_COLS_WITH_TIME = (*_ENTRY_COLS, "created_at")
_SEARCH_COLS = (*_ENTRY_COLS, "similarity")


def _rows_to_dicts(rows, cols: tuple[str, ...]) -> list[dict]:
    return [_row_to_dict(row, cols) for row in rows]


def _row_to_dict(row, cols: tuple[str, ...]) -> dict:
    d = dict(zip(cols, row, strict=False))
    d["id"] = str(d["id"])
    return d


def _search_by_embedding(cur, emb_str: str, domain_filter: str, params: tuple, limit: int) -> list[dict]:
    cur.execute(
        f"""SELECT id, tier, domain, title, content, source,
                  1 - (embedding <=> %s::vector) AS similarity
           FROM knowledge_entries
           WHERE is_active = TRUE {domain_filter}
                 AND (expires_at IS NULL OR expires_at > NOW())
           ORDER BY embedding <=> %s::vector ASC
           LIMIT %s""",
        (*params, emb_str, limit),
    )
    return _rows_to_dicts(cur.fetchall(), _SEARCH_COLS)


def _fetch_entries(cur, where: str, params: tuple, order: str = "created_at") -> list[dict]:
    cur.execute(
        f"""SELECT id, tier, domain, title, content, source
           FROM knowledge_entries
           WHERE is_active = TRUE AND {where}
           ORDER BY {order}""",
        params,
    )
    return _rows_to_dicts(cur.fetchall(), _ENTRY_COLS)


class KnowledgeRepo(BasePostgresRepo):

    def save_knowledge_entry(self, tier: str, domain: str, title: str, content: str, source: str,  # noqa: PLR0913
                             *,
                             embedding: list[float] | None = None,
                             user_id: str | None = None,
                             source_url: str | None = None,
                             expires_at=None,
                             parent_id: str | None = None) -> str:
        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO knowledge_entries (tier, domain, title, content, source, embedding,
                              user_id, source_url, expires_at, parent_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (tier, domain, title, content, source,
                 str(embedding) if embedding is not None else None,
                 user_id, source_url, expires_at, parent_id),
            )
            return str(cur.fetchone()[0])

    def update_knowledge_entry(self, entry_id: str, content: str, embedding: list[float] | None = None) -> bool:
        with self._cursor() as cur:
            cur.execute(
                """UPDATE knowledge_entries
                   SET content = %s, embedding = %s, updated_at = NOW()
                   WHERE id = %s""",
                (content, str(embedding) if embedding is not None else None, entry_id),
            )
            return cur.rowcount > 0

    def search_knowledge(self, query_embedding: list[float], domain: str | None = None, limit: int = 5) -> list[dict]:
        emb_str = str(query_embedding)
        with self._cursor() as cur:
            if domain is not None:
                return _search_by_embedding(cur, emb_str, "AND domain = %s", (emb_str, domain), limit)
            return _search_by_embedding(cur, emb_str, "", (emb_str,), limit)

    def search_knowledge_multi_domain(
        self, query_embedding: list[float],
        domains: list[str] | None = None,
        limit: int = 5,
    ) -> list[dict]:
        emb_str = str(query_embedding)
        with self._cursor() as cur:
            if domains is not None:
                return _search_by_embedding(cur, emb_str, "AND domain = ANY(%s)", (emb_str, domains), limit)
            return _search_by_embedding(cur, emb_str, "", (emb_str,), limit)

    def get_knowledge_by_tier(self, tier: str) -> list[dict]:
        with self._cursor() as cur:
            return _fetch_entries(cur, "tier = %s", (tier,), order="domain, created_at")

    def get_domain_context(self, domain: str) -> list[dict]:
        """Fetch core (global) + meta (domain-wide) entries for a domain."""
        with self._cursor() as cur:
            return _fetch_entries(
                cur, "tier = 'core' OR (tier = 'meta' AND domain = %s)", (domain,), order="tier, created_at",
            )

    def get_multi_domain_context(self, domains: list[str]) -> list[dict]:
        """Fetch core (global) + meta entries for multiple domains."""
        with self._cursor() as cur:
            return _fetch_entries(
                cur, "tier = 'core' OR (tier = 'meta' AND domain = ANY(%s))", (domains,), order="tier, created_at",
            )

    def get_knowledge_by_domain(self, domain: str) -> list[dict]:
        with self._cursor() as cur:
            return _fetch_entries(cur, "domain = %s", (domain,))

    def list_knowledge(self, domain: str | None = None, tier: str | None = None) -> list[dict]:
        sql = "SELECT id, tier, domain, title, content, source, created_at FROM knowledge_entries WHERE is_active = TRUE"
        params: list = []
        if domain is not None:
            sql += " AND domain = %s"
            params.append(domain)
        if tier is not None:
            sql += " AND tier = %s"
            params.append(tier)
        sql += " ORDER BY tier, domain, created_at"
        with self._cursor() as cur:
            cur.execute(sql, tuple(params))
            return _rows_to_dicts(cur.fetchall(), _ENTRY_COLS_WITH_TIME)

    def get_knowledge_entry(self, entry_id: str) -> dict | None:
        with self._cursor() as cur:
            cur.execute(
                """SELECT id, tier, domain, title, content, source, created_at
                   FROM knowledge_entries
                   WHERE id = %s AND is_active = TRUE""",
                (entry_id,),
            )
            row = cur.fetchone()
            return _row_to_dict(row, _ENTRY_COLS_WITH_TIME) if row else None

    def deactivate_knowledge(self, entry_id: str) -> bool:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE knowledge_entries SET is_active = FALSE, updated_at = NOW() WHERE id = %s",
                (entry_id,),
            )
            return cur.rowcount > 0

    # ── Knowledge domains ────────────────────────────────────────────

    def list_domains(self) -> list[dict]:
        with self._cursor() as cur:
            cur.execute("SELECT name, description FROM knowledge_domains ORDER BY name")
            return [{"name": row[0], "description": row[1]} for row in cur.fetchall()]

    def find_by_source_url(self, source_url: str) -> dict | None:
        """Find active knowledge entry by source_url."""
        with self._cursor() as cur:
            cur.execute(
                """SELECT id, tier, domain, title, content, source, source_url
                   FROM knowledge_entries
                   WHERE source_url = %s AND is_active = TRUE
                   ORDER BY created_at DESC LIMIT 1""",
                (source_url,),
            )
            row = cur.fetchone()
            cols = (*_ENTRY_COLS, "source_url")
            return _row_to_dict(row, cols) if row else None

    def get_or_create_domain(self, name: str, description: str = "") -> str:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO knowledge_domains (name, description) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING",
                (name, description),
            )
            return name
