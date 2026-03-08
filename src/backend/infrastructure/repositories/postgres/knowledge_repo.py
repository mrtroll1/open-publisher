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


def _visibility_clause(role: str, user_id: str | None = None,
                        environment: str | None = None) -> tuple[str, list]:
    """Build WHERE fragment for visibility filtering.

    Visibility levels:
        public       — everyone
        environment  — same environment + admins
        role:editor  — editors + admins
        role:admin   — admins only
        user         — owner (user_id) + admins
    """
    if role == "admin":
        return "", []
    parts = ["visibility = 'public'"]
    params: list = []
    if environment:
        parts.append("(visibility = 'environment' AND environment_id = %s)")
        params.append(environment)
    if role == "editor":
        parts.append("visibility = 'role:editor'")
    if user_id:
        parts.append("(visibility = 'user' AND user_id = %s)")
        params.append(user_id)
    return "AND (" + " OR ".join(parts) + ")", params


def _search_by_embedding(cur, emb_str: str, *, where_extra: str = "",
                          params_extra: tuple = (), limit: int = 5) -> list[dict]:
    cur.execute(
        f"""SELECT id, tier, domain, title, content, source,
                  1 - (embedding <=> %s::vector) AS similarity
           FROM unit_of_knowledge
           WHERE is_active = TRUE
                 AND (expires_at IS NULL OR expires_at > NOW())
                 {where_extra}
           ORDER BY embedding <=> %s::vector ASC
           LIMIT %s""",
        (emb_str, *params_extra, emb_str, limit),
    )
    return _rows_to_dicts(cur.fetchall(), _SEARCH_COLS)


def _fetch_entries(cur, where: str, params: tuple, order: str = "created_at") -> list[dict]:
    cur.execute(
        f"""SELECT id, tier, domain, title, content, source
           FROM unit_of_knowledge
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
                             parent_id: str | None = None,
                             visibility: str = "public",
                             environment_id: str | None = None,
                             source_type: str = "") -> str:
        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO unit_of_knowledge
                          (tier, domain, title, content, source, embedding,
                           user_id, source_url, expires_at, parent_id,
                           visibility, environment_id, source_type)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (tier, domain, title, content, source,
                 str(embedding) if embedding is not None else None,
                 user_id, source_url, expires_at, parent_id,
                 visibility, environment_id, source_type),
            )
            return str(cur.fetchone()[0])

    def update_knowledge_entry(self, entry_id: str, content: str, embedding: list[float] | None = None) -> bool:
        with self._cursor() as cur:
            cur.execute(
                """UPDATE unit_of_knowledge
                   SET content = %s, embedding = %s, updated_at = NOW()
                   WHERE id = %s""",
                (content, str(embedding) if embedding is not None else None, entry_id),
            )
            return cur.rowcount > 0

    def search_knowledge(self, query_embedding: list[float], *,  # noqa: PLR0913
                         role: str = "admin", user_id: str | None = None,
                         environment: str | None = None,
                         domain: str | None = None, limit: int = 5) -> list[dict]:
        emb_str = str(query_embedding)
        vis_clause, vis_params = _visibility_clause(role, user_id, environment)
        domain_clause = "AND domain = %s" if domain else ""
        domain_params = [domain] if domain else []
        where_extra = f"{vis_clause} {domain_clause}"
        params_extra = (*vis_params, *domain_params)
        with self._cursor() as cur:
            return _search_by_embedding(cur, emb_str, where_extra=where_extra,
                                        params_extra=params_extra, limit=limit)

    def get_knowledge_by_tier(self, tier: str) -> list[dict]:
        with self._cursor() as cur:
            return _fetch_entries(cur, "tier = %s", (tier,), order="domain, created_at")

    def get_visible_meta(self, *, role: str = "admin", user_id: str | None = None,
                         environment: str | None = None) -> list[dict]:
        """Meta entries visible to caller."""
        vis_clause, vis_params = _visibility_clause(role, user_id, environment)
        where = f"tier = 'meta' {vis_clause}"
        with self._cursor() as cur:
            return _fetch_entries(cur, where, tuple(vis_params), order="domain, created_at")

    def get_domain_context(self, domain: str) -> list[dict]:
        """Core (global) + meta (domain-wide) entries. For internal pipelines."""
        with self._cursor() as cur:
            return _fetch_entries(
                cur, "tier = 'core' OR (tier = 'meta' AND domain = %s)", (domain,), order="tier, created_at",
            )

    def get_knowledge_by_domain(self, domain: str) -> list[dict]:
        with self._cursor() as cur:
            return _fetch_entries(cur, "domain = %s", (domain,))

    def list_knowledge(self, domain: str | None = None, tier: str | None = None) -> list[dict]:
        sql = "SELECT id, tier, domain, title, content, source, created_at FROM unit_of_knowledge WHERE is_active = TRUE"
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
                   FROM unit_of_knowledge
                   WHERE id = %s AND is_active = TRUE""",
                (entry_id,),
            )
            row = cur.fetchone()
            return _row_to_dict(row, _ENTRY_COLS_WITH_TIME) if row else None

    def deactivate_knowledge(self, entry_id: str) -> bool:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE unit_of_knowledge SET is_active = FALSE, updated_at = NOW() WHERE id = %s",
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
                   FROM unit_of_knowledge
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
