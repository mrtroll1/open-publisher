"""Entity repository."""

from __future__ import annotations

import json

from backend.infrastructure.repositories.postgres.base import BasePostgresRepo


class EntityRepo(BasePostgresRepo):

    def save_entity(self, kind: str, name: str,
                    external_ids: dict | None = None,
                    summary: str = "",
                    embedding: list[float] | None = None) -> str:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO entities (kind, name, external_ids, summary, embedding)
                   VALUES (%s, %s, %s, %s, %s)
                   RETURNING id""",
                (kind, name,
                 json.dumps(external_ids) if external_ids is not None else "{}",
                 summary,
                 str(embedding) if embedding is not None else None),
            )
            return str(cur.fetchone()[0])

    def get_entity(self, entity_id: str) -> dict | None:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, kind, name, external_ids, summary, embedding,
                          created_at, updated_at
                   FROM entities WHERE id = %s""",
                (entity_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = ["id", "kind", "name", "external_ids", "summary", "embedding",
                    "created_at", "updated_at"]
            d = dict(zip(cols, row))
            d["id"] = str(d["id"])
            return d

    def find_entity_by_external_id(self, key: str, value) -> dict | None:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, kind, name, external_ids, summary, embedding,
                          created_at, updated_at
                   FROM entities
                   WHERE external_ids->>%s = %s""",
                (key, str(value)),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = ["id", "kind", "name", "external_ids", "summary", "embedding",
                    "created_at", "updated_at"]
            d = dict(zip(cols, row))
            d["id"] = str(d["id"])
            return d

    def find_entities_by_name(self, name_query: str, limit: int = 5) -> list[dict]:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, kind, name, external_ids, summary, embedding,
                          created_at, updated_at
                   FROM entities
                   WHERE name ILIKE %s
                   ORDER BY name
                   LIMIT %s""",
                (f"%{name_query}%", limit),
            )
            cols = ["id", "kind", "name", "external_ids", "summary", "embedding",
                    "created_at", "updated_at"]
            rows = []
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                d["id"] = str(d["id"])
                rows.append(d)
            return rows

    def update_entity(self, entity_id: str, **fields) -> bool:
        allowed = {"name", "summary", "external_ids", "embedding"}
        to_update = {k: v for k, v in fields.items() if k in allowed}
        if not to_update:
            return False
        set_parts = []
        params: list = []
        for col, val in to_update.items():
            set_parts.append(f"{col} = %s")
            if col == "external_ids":
                params.append(json.dumps(val) if val is not None else "{}")
            elif col == "embedding":
                params.append(str(val) if val is not None else None)
            else:
                params.append(val)
        set_parts.append("updated_at = NOW()")
        sql = f"UPDATE entities SET {', '.join(set_parts)} WHERE id = %s"
        params.append(entity_id)
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            return cur.rowcount > 0

    def search_entities(self, query_embedding: list[float], limit: int = 5) -> list[dict]:
        conn = self._get_conn()
        emb_str = str(query_embedding)
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, kind, name, external_ids, summary, embedding,
                          created_at, updated_at,
                          1 - (embedding <=> %s::vector) AS similarity
                   FROM entities
                   WHERE embedding IS NOT NULL
                   ORDER BY embedding <=> %s::vector ASC
                   LIMIT %s""",
                (emb_str, emb_str, limit),
            )
            cols = ["id", "kind", "name", "external_ids", "summary", "embedding",
                    "created_at", "updated_at", "similarity"]
            rows = []
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                d["id"] = str(d["id"])
                rows.append(d)
            return rows

    def get_entity_knowledge(self, entity_id: str, limit: int = 10) -> list[dict]:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, tier, domain, title, content, source, created_at
                   FROM knowledge_entries
                   WHERE entity_id = %s AND is_active = TRUE
                   ORDER BY created_at DESC
                   LIMIT %s""",
                (entity_id, limit),
            )
            cols = ["id", "tier", "domain", "title", "content", "source", "created_at"]
            rows = []
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                d["id"] = str(d["id"])
                rows.append(d)
            return rows

    def list_entities(self, kind: str | None = None) -> list[dict]:
        conn = self._get_conn()
        with conn.cursor() as cur:
            if kind is not None:
                cur.execute(
                    """SELECT id, kind, name, external_ids, summary, embedding,
                              created_at, updated_at
                       FROM entities
                       WHERE kind = %s
                       ORDER BY name""",
                    (kind,),
                )
            else:
                cur.execute(
                    """SELECT id, kind, name, external_ids, summary, embedding,
                              created_at, updated_at
                       FROM entities
                       ORDER BY name"""
                )
            cols = ["id", "kind", "name", "external_ids", "summary", "embedding",
                    "created_at", "updated_at"]
            rows = []
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                d["id"] = str(d["id"])
                rows.append(d)
            return rows
