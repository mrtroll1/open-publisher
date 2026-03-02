from unittest.mock import MagicMock

from backend.infrastructure.gateways.db_gateway import DbGateway


def _make_gw() -> tuple[DbGateway, MagicMock]:
    """Create a DbGateway with a mocked connection/cursor."""
    gw = DbGateway()
    mock_cursor = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_cursor)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    mock_conn = MagicMock()
    mock_conn.closed = False
    mock_conn.cursor.return_value = mock_ctx
    gw._conn = mock_conn
    return gw, mock_cursor


# ===================================================================
#  save_knowledge_entry
# ===================================================================

class TestSaveKnowledgeEntry:

    def test_insert_without_embedding(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = ("entry-uuid-1",)

        result = gw.save_knowledge_entry(
            tier="domain", scope="editorial", title="Style guide",
            content="Use active voice.", source="seed",
        )

        assert result == "entry-uuid-1"
        sql, params = cur.execute.call_args[0]
        assert "INSERT INTO knowledge_entries" in sql
        assert "RETURNING id" in sql
        assert params == ("domain", "editorial", "Style guide", "Use active voice.", "seed", None)

    def test_insert_with_embedding(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = ("entry-uuid-2",)
        emb = [0.1, 0.2, 0.3]

        result = gw.save_knowledge_entry(
            tier="process", scope="payments", title="Invoice rules",
            content="Check INN length.", source="learned", embedding=emb,
        )

        assert result == "entry-uuid-2"
        _, params = cur.execute.call_args[0]
        assert params == ("process", "payments", "Invoice rules", "Check INN length.", "learned", str(emb))


# ===================================================================
#  update_knowledge_entry
# ===================================================================

class TestUpdateKnowledgeEntry:

    def test_update_with_embedding(self):
        gw, cur = _make_gw()
        emb = [0.4, 0.5, 0.6]

        gw.update_knowledge_entry("entry-uuid-1", content="Updated content.", embedding=emb)

        sql, params = cur.execute.call_args[0]
        assert "UPDATE knowledge_entries" in sql
        assert "updated_at = NOW()" in sql
        assert params == ("Updated content.", str(emb), "entry-uuid-1")

    def test_update_without_embedding(self):
        gw, cur = _make_gw()

        gw.update_knowledge_entry("entry-uuid-1", content="New content.")

        _, params = cur.execute.call_args[0]
        assert params == ("New content.", None, "entry-uuid-1")


# ===================================================================
#  search_knowledge
# ===================================================================

class TestSearchKnowledge:

    def test_search_without_scope(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = [
            ("id-1", "domain", "editorial", "Title", "Content", "seed", 0.95),
            ("id-2", "process", "payments", "Title2", "Content2", "learned", 0.80),
        ]
        emb = [0.1, 0.2, 0.3]

        result = gw.search_knowledge(query_embedding=emb, limit=2)

        assert len(result) == 2
        assert result[0]["id"] == "id-1"
        assert result[0]["similarity"] == 0.95
        assert result[1]["id"] == "id-2"
        sql, params = cur.execute.call_args[0]
        assert "1 - (embedding <=> %s::vector) AS similarity" in sql
        assert "WHERE is_active = TRUE" in sql
        assert "scope" not in sql.split("WHERE")[1].split("ORDER")[0] or "AND scope" not in sql
        assert params == (str(emb), str(emb), 2)

    def test_search_with_scope(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = [
            ("id-3", "domain", "editorial", "T", "C", "seed", 0.9),
        ]
        emb = [0.1, 0.2]

        result = gw.search_knowledge(query_embedding=emb, scope="editorial", limit=3)

        assert len(result) == 1
        assert result[0]["scope"] == "editorial"
        sql, params = cur.execute.call_args[0]
        assert "AND scope = %s" in sql
        assert params == (str(emb), "editorial", str(emb), 3)

    def test_search_empty_results(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = []

        result = gw.search_knowledge(query_embedding=[0.0, 0.0])

        assert result == []


# ===================================================================
#  get_knowledge_by_tier
# ===================================================================

class TestGetKnowledgeByTier:

    def test_returns_entries(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = [
            ("id-1", "domain", "editorial", "Style", "Use active voice.", "seed"),
            ("id-2", "domain", "editorial", "Tone", "Be concise.", "seed"),
        ]

        result = gw.get_knowledge_by_tier("domain")

        assert len(result) == 2
        assert result[0]["id"] == "id-1"
        assert result[1]["content"] == "Be concise."
        sql, params = cur.execute.call_args[0]
        assert "WHERE tier = %s AND is_active = TRUE" in sql
        assert "ORDER BY scope, created_at" in sql
        assert params == ("domain",)

    def test_empty_tier(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = []

        result = gw.get_knowledge_by_tier("nonexistent")

        assert result == []


# ===================================================================
#  get_knowledge_by_scope
# ===================================================================

class TestGetKnowledgeByScope:

    def test_returns_entries(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = [
            ("id-1", "domain", "payments", "Rule1", "Check INN.", "seed"),
        ]

        result = gw.get_knowledge_by_scope("payments")

        assert len(result) == 1
        assert result[0]["id"] == "id-1"
        assert result[0]["scope"] == "payments"
        sql, params = cur.execute.call_args[0]
        assert "WHERE scope = %s AND is_active = TRUE" in sql
        assert "ORDER BY created_at" in sql
        assert params == ("payments",)

    def test_empty_scope(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = []

        result = gw.get_knowledge_by_scope("empty")

        assert result == []


# ===================================================================
#  list_knowledge
# ===================================================================

class TestListKnowledge:

    def test_no_filters(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = [
            ("id-1", "domain", "editorial", "Style", "seed", "2026-01-01"),
        ]

        result = gw.list_knowledge()

        assert len(result) == 1
        assert result[0]["id"] == "id-1"
        sql, params = cur.execute.call_args[0]
        assert "WHERE is_active = TRUE" in sql
        assert "AND scope" not in sql
        assert "AND tier" not in sql
        assert "ORDER BY tier, scope, created_at" in sql
        assert params == ()

    def test_scope_filter(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = []

        gw.list_knowledge(scope="editorial")

        sql, params = cur.execute.call_args[0]
        assert "AND scope = %s" in sql
        assert "AND tier" not in sql
        assert params == ("editorial",)

    def test_tier_filter(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = []

        gw.list_knowledge(tier="domain")

        sql, params = cur.execute.call_args[0]
        assert "AND tier = %s" in sql
        assert "AND scope" not in sql
        assert params == ("domain",)

    def test_both_filters(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = []

        gw.list_knowledge(scope="editorial", tier="domain")

        sql, params = cur.execute.call_args[0]
        assert "AND scope = %s" in sql
        assert "AND tier = %s" in sql
        assert params == ("editorial", "domain")


# ===================================================================
#  deactivate_knowledge
# ===================================================================

class TestDeactivateKnowledge:

    def test_deactivates_entry(self):
        gw, cur = _make_gw()

        gw.deactivate_knowledge("entry-uuid-1")

        sql, params = cur.execute.call_args[0]
        assert "UPDATE knowledge_entries" in sql
        assert "SET is_active = FALSE" in sql
        assert "updated_at = NOW()" in sql
        assert params == ("entry-uuid-1",)
