import json
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
#  save_entity + get_entity
# ===================================================================

class TestSaveAndGetEntity:

    def test_save_and_get_entity(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = ("entity-uuid-1",)

        result = gw.save_entity(
            kind="person",
            name="John Doe",
            external_ids={"telegram_user_id": 123},
            summary="Editor at Republic.",
        )

        assert result == "entity-uuid-1"
        sql, params = cur.execute.call_args[0]
        assert "INSERT INTO entities" in sql
        assert "RETURNING id" in sql
        assert params == (
            "person", "John Doe",
            json.dumps({"telegram_user_id": 123}),
            "Editor at Republic.", None,
        )

    def test_save_entity_defaults(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = ("entity-uuid-2",)

        result = gw.save_entity(kind="organization", name="Republic")

        assert result == "entity-uuid-2"
        _, params = cur.execute.call_args[0]
        assert params == ("organization", "Republic", "{}", "", None)

    def test_get_entity_found(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = (
            "entity-uuid-1", "person", "John Doe",
            {"telegram_user_id": 123}, "Editor at Republic.", None,
            "2026-01-01", "2026-01-01",
        )

        result = gw.get_entity("entity-uuid-1")

        assert result is not None
        assert result["id"] == "entity-uuid-1"
        assert result["kind"] == "person"
        assert result["name"] == "John Doe"
        assert result["external_ids"] == {"telegram_user_id": 123}
        assert result["summary"] == "Editor at Republic."
        sql, params = cur.execute.call_args[0]
        assert "FROM entities WHERE id = %s" in sql
        assert params == ("entity-uuid-1",)

    def test_get_entity_not_found(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = None

        result = gw.get_entity("nonexistent")

        assert result is None


# ===================================================================
#  find_entity_by_external_id
# ===================================================================

class TestFindEntityByExternalId:

    def test_find_entity_by_external_id(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = (
            "entity-uuid-1", "person", "John Doe",
            {"telegram_user_id": "123"}, "Editor.", None,
            "2026-01-01", "2026-01-01",
        )

        result = gw.find_entity_by_external_id("telegram_user_id", 123)

        assert result is not None
        assert result["id"] == "entity-uuid-1"
        assert result["name"] == "John Doe"
        sql, params = cur.execute.call_args[0]
        assert "external_ids->>%s = %s" in sql
        assert params == ("telegram_user_id", "123")

    def test_find_entity_by_external_id_not_found(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = None

        result = gw.find_entity_by_external_id("email", "nobody@example.com")

        assert result is None


# ===================================================================
#  find_entities_by_name
# ===================================================================

class TestFindEntitiesByName:

    def test_find_entities_by_name(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = [
            ("id-1", "person", "John Doe", {}, "Editor.", None, "2026-01-01", "2026-01-01"),
            ("id-2", "person", "John Smith", {}, "Writer.", None, "2026-01-01", "2026-01-01"),
        ]

        result = gw.find_entities_by_name("John")

        assert len(result) == 2
        assert result[0]["id"] == "id-1"
        assert result[1]["name"] == "John Smith"
        sql, params = cur.execute.call_args[0]
        assert "ILIKE" in sql
        assert params == ("%John%", 5)

    def test_find_entities_by_name_empty(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = []

        result = gw.find_entities_by_name("Nobody")

        assert result == []


# ===================================================================
#  update_entity
# ===================================================================

class TestUpdateEntityPartial:

    def test_update_entity_partial(self):
        gw, cur = _make_gw()
        cur.rowcount = 1

        result = gw.update_entity("entity-uuid-1", summary="Updated summary.")

        assert result is True
        sql, params = cur.execute.call_args[0]
        assert "UPDATE entities SET" in sql
        assert "summary = %s" in sql
        assert "updated_at = NOW()" in sql
        assert params == ("Updated summary.", "entity-uuid-1")

    def test_update_multiple_fields(self):
        gw, cur = _make_gw()
        cur.rowcount = 1

        result = gw.update_entity(
            "entity-uuid-1",
            name="Jane Doe",
            external_ids={"email": "jane@example.com"},
        )

        assert result is True
        sql, params = cur.execute.call_args[0]
        assert "name = %s" in sql
        assert "external_ids = %s" in sql
        assert params[-1] == "entity-uuid-1"

    def test_update_returns_false_when_not_found(self):
        gw, cur = _make_gw()
        cur.rowcount = 0

        result = gw.update_entity("nonexistent", summary="x")

        assert result is False

    def test_update_ignores_unknown_fields(self):
        gw, cur = _make_gw()

        result = gw.update_entity("entity-uuid-1", bogus_field="value")

        assert result is False
        cur.execute.assert_not_called()


# ===================================================================
#  get_entity_knowledge
# ===================================================================

class TestGetEntityKnowledge:

    def test_get_entity_knowledge(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = [
            ("k-id-1", "specific", "contractor", "Info", "Content1", "admin", "2026-01-02"),
            ("k-id-2", "specific", "contractor", "More info", "Content2", "admin", "2026-01-01"),
        ]

        result = gw.get_entity_knowledge("entity-uuid-1")

        assert len(result) == 2
        assert result[0]["id"] == "k-id-1"
        assert result[1]["id"] == "k-id-2"
        sql, params = cur.execute.call_args[0]
        assert "WHERE entity_id = %s AND is_active = TRUE" in sql
        assert "ORDER BY created_at DESC" in sql
        assert params == ("entity-uuid-1", 10)

    def test_get_entity_knowledge_empty(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = []

        result = gw.get_entity_knowledge("entity-uuid-1")

        assert result == []


# ===================================================================
#  list_entities
# ===================================================================

class TestListEntitiesByKind:

    def test_list_entities_by_kind(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = [
            ("id-1", "person", "Alice", {}, "Writer.", None, "2026-01-01", "2026-01-01"),
            ("id-2", "person", "Bob", {}, "Editor.", None, "2026-01-01", "2026-01-01"),
        ]

        result = gw.list_entities(kind="person")

        assert len(result) == 2
        assert result[0]["kind"] == "person"
        assert result[1]["name"] == "Bob"
        sql, params = cur.execute.call_args[0]
        assert "WHERE kind = %s" in sql
        assert "ORDER BY name" in sql
        assert params == ("person",)

    def test_list_entities_all(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = [
            ("id-1", "person", "Alice", {}, "Writer.", None, "2026-01-01", "2026-01-01"),
            ("id-2", "organization", "Republic", {}, "Media.", None, "2026-01-01", "2026-01-01"),
        ]

        result = gw.list_entities()

        assert len(result) == 2
        sql = cur.execute.call_args[0][0]
        assert "WHERE kind" not in sql
        assert "ORDER BY name" in sql

    def test_list_entities_empty(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = []

        result = gw.list_entities(kind="competitor")

        assert result == []
