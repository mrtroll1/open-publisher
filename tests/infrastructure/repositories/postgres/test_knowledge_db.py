from unittest.mock import MagicMock

from backend.infrastructure.repositories.postgres import DbGateway


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
            tier="specific", domain="editorial", title="Style guide",
            content="Use active voice.", source="seed",
        )

        assert result == "entry-uuid-1"
        sql, params = cur.execute.call_args[0]
        assert "INSERT INTO knowledge_entries" in sql
        assert "RETURNING id" in sql
        assert params == ("specific", "editorial", "Style guide", "Use active voice.", "seed", None)

    def test_insert_with_embedding(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = ("entry-uuid-2",)
        emb = [0.1, 0.2, 0.3]

        result = gw.save_knowledge_entry(
            tier="process", domain="payments", title="Invoice rules",
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
        cur.rowcount = 1
        emb = [0.4, 0.5, 0.6]

        result = gw.update_knowledge_entry("entry-uuid-1", content="Updated content.", embedding=emb)

        assert result is True
        sql, params = cur.execute.call_args[0]
        assert "UPDATE knowledge_entries" in sql
        assert "updated_at = NOW()" in sql
        assert params == ("Updated content.", str(emb), "entry-uuid-1")

    def test_update_without_embedding(self):
        gw, cur = _make_gw()
        cur.rowcount = 1

        gw.update_knowledge_entry("entry-uuid-1", content="New content.")

        _, params = cur.execute.call_args[0]
        assert params == ("New content.", None, "entry-uuid-1")

    def test_returns_false_when_not_found(self):
        gw, cur = _make_gw()
        cur.rowcount = 0

        result = gw.update_knowledge_entry("nonexistent-uuid", content="text")

        assert result is False


# ===================================================================
#  search_knowledge
# ===================================================================

class TestSearchKnowledge:

    def test_search_without_domain(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = [
            ("id-1", "specific", "editorial", "Title", "Content", "seed", 0.95),
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
        assert "AND domain" not in sql.split("WHERE")[1].split("ORDER")[0]
        assert params == (str(emb), str(emb), 2)

    def test_search_with_domain(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = [
            ("id-3", "specific", "editorial", "T", "C", "seed", 0.9),
        ]
        emb = [0.1, 0.2]

        result = gw.search_knowledge(query_embedding=emb, domain="editorial", limit=3)

        assert len(result) == 1
        assert result[0]["domain"] == "editorial"
        sql, params = cur.execute.call_args[0]
        assert "AND domain = %s" in sql
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
            ("id-1", "specific", "editorial", "Style", "Use active voice.", "seed"),
            ("id-2", "specific", "editorial", "Tone", "Be concise.", "seed"),
        ]

        result = gw.get_knowledge_by_tier("specific")

        assert len(result) == 2
        assert result[0]["id"] == "id-1"
        assert result[1]["content"] == "Be concise."
        sql, params = cur.execute.call_args[0]
        assert "WHERE tier = %s AND is_active = TRUE" in sql
        assert "ORDER BY domain, created_at" in sql
        assert params == ("specific",)

    def test_empty_tier(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = []

        result = gw.get_knowledge_by_tier("nonexistent")

        assert result == []


# ===================================================================
#  get_domain_context
# ===================================================================

class TestGetDomainContext:

    def test_returns_core_and_meta_entries(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = [
            ("id-1", "core", "identity", "Who we are", "Republic is...", "seed"),
            ("id-2", "meta", "tech_support", "FAQ rules", "Always check...", "seed"),
        ]

        result = gw.get_domain_context("tech_support")

        assert len(result) == 2
        assert result[0]["tier"] == "core"
        assert result[1]["tier"] == "meta"
        sql, params = cur.execute.call_args[0]
        assert "tier = 'core'" in sql
        assert "tier = 'meta'" in sql
        assert params == ("tech_support",)

    def test_empty(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = []

        result = gw.get_domain_context("empty_domain")

        assert result == []


# ===================================================================
#  get_knowledge_by_domain
# ===================================================================

class TestGetKnowledgeByDomain:

    def test_returns_entries(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = [
            ("id-1", "specific", "payments", "Rule1", "Check INN.", "seed"),
        ]

        result = gw.get_knowledge_by_domain("payments")

        assert len(result) == 1
        assert result[0]["id"] == "id-1"
        assert result[0]["domain"] == "payments"
        sql, params = cur.execute.call_args[0]
        assert "WHERE domain = %s AND is_active = TRUE" in sql
        assert "ORDER BY created_at" in sql
        assert params == ("payments",)

    def test_empty_domain(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = []

        result = gw.get_knowledge_by_domain("empty")

        assert result == []


# ===================================================================
#  list_knowledge
# ===================================================================

class TestListKnowledge:

    def test_no_filters(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = [
            ("id-1", "specific", "editorial", "Style", "Content", "seed", "2026-01-01"),
        ]

        result = gw.list_knowledge()

        assert len(result) == 1
        assert result[0]["id"] == "id-1"
        sql, params = cur.execute.call_args[0]
        assert "WHERE is_active = TRUE" in sql
        assert "AND domain" not in sql
        assert "AND tier" not in sql
        assert "ORDER BY tier, domain, created_at" in sql
        assert params == ()

    def test_domain_filter(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = []

        gw.list_knowledge(domain="editorial")

        sql, params = cur.execute.call_args[0]
        assert "AND domain = %s" in sql
        assert "AND tier" not in sql
        assert params == ("editorial",)

    def test_tier_filter(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = []

        gw.list_knowledge(tier="specific")

        sql, params = cur.execute.call_args[0]
        assert "AND tier = %s" in sql
        assert "AND domain" not in sql
        assert params == ("specific",)

    def test_both_filters(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = []

        gw.list_knowledge(domain="editorial", tier="specific")

        sql, params = cur.execute.call_args[0]
        assert "AND domain = %s" in sql
        assert "AND tier = %s" in sql
        assert params == ("editorial", "specific")


# ===================================================================
#  list_domains
# ===================================================================

class TestListDomains:

    def test_returns_domains(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = [
            ("general", "General knowledge"),
            ("tech_support", "Tech support"),
        ]

        result = gw.list_domains()

        assert len(result) == 2
        assert result[0] == {"name": "general", "description": "General knowledge"}
        assert result[1] == {"name": "tech_support", "description": "Tech support"}

    def test_empty(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = []

        result = gw.list_domains()

        assert result == []


# ===================================================================
#  get_or_create_domain
# ===================================================================

class TestGetOrCreateDomain:

    def test_returns_name(self):
        gw, cur = _make_gw()

        result = gw.get_or_create_domain("new_domain", "Description")

        assert result == "new_domain"
        sql, params = cur.execute.call_args[0]
        assert "INSERT INTO knowledge_domains" in sql
        assert "ON CONFLICT (name) DO NOTHING" in sql
        assert params == ("new_domain", "Description")

    def test_default_description(self):
        gw, cur = _make_gw()

        gw.get_or_create_domain("test")

        _, params = cur.execute.call_args[0]
        assert params == ("test", "")


# ===================================================================
#  deactivate_knowledge
# ===================================================================

class TestDeactivateKnowledge:

    def test_deactivates_entry(self):
        gw, cur = _make_gw()
        cur.rowcount = 1

        result = gw.deactivate_knowledge("entry-uuid-1")

        assert result is True
        sql, params = cur.execute.call_args[0]
        assert "UPDATE knowledge_entries" in sql
        assert "SET is_active = FALSE" in sql
        assert "updated_at = NOW()" in sql
        assert params == ("entry-uuid-1",)

    def test_returns_false_when_not_found(self):
        gw, cur = _make_gw()
        cur.rowcount = 0

        result = gw.deactivate_knowledge("nonexistent-uuid")

        assert result is False
