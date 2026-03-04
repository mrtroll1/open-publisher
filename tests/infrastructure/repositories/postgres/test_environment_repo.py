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
#  save_environment + get_environment
# ===================================================================

class TestSaveAndGetEnvironment:

    def test_save_and_get_environment(self):
        gw, cur = _make_gw()

        result = gw.save_environment(
            name="admin_dm",
            description="Admin chat",
            system_context="Full access.",
            allowed_domains=None,
        )

        assert result == "admin_dm"
        sql, params = cur.execute.call_args[0]
        assert "INSERT INTO environments" in sql
        assert "ON CONFLICT (name) DO UPDATE" in sql
        assert params == ("admin_dm", "Admin chat", "Full access.", None)

    def test_save_with_allowed_domains(self):
        gw, cur = _make_gw()

        result = gw.save_environment(
            name="editorial_group",
            description="Editorial",
            system_context="Group context.",
            allowed_domains=["tech_support", "editorial"],
        )

        assert result == "editorial_group"
        _, params = cur.execute.call_args[0]
        assert params == ("editorial_group", "Editorial", "Group context.", ["tech_support", "editorial"])

    def test_get_environment_found(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = (
            "admin_dm", "Admin chat", "Full access.", None,
            "2026-01-01", "2026-01-01",
        )

        result = gw.get_environment("admin_dm")

        assert result is not None
        assert result["name"] == "admin_dm"
        assert result["description"] == "Admin chat"
        assert result["system_context"] == "Full access."
        assert result["allowed_domains"] is None
        sql, params = cur.execute.call_args[0]
        assert "FROM environments WHERE name = %s" in sql
        assert params == ("admin_dm",)

    def test_get_environment_not_found(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = None

        result = gw.get_environment("nonexistent")

        assert result is None


# ===================================================================
#  get_environment_by_chat_id
# ===================================================================

class TestGetEnvironmentByChatId:

    def test_get_environment_by_chat_id(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = (
            "admin_dm", "Admin chat", "Full access.",
            None, "2026-01-01", "2026-01-01",
        )

        result = gw.get_environment_by_chat_id(12345)

        assert result is not None
        assert result["name"] == "admin_dm"
        assert result["system_context"] == "Full access."
        sql, params = cur.execute.call_args[0]
        assert "JOIN environments e ON e.name = b.environment" in sql
        assert "WHERE b.chat_id = %s" in sql
        assert params == (12345,)

    def test_get_environment_by_chat_id_unbound_returns_none(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = None

        result = gw.get_environment_by_chat_id(99999)

        assert result is None


# ===================================================================
#  bind_chat + rebind
# ===================================================================

class TestBindChat:

    def test_bind_chat_and_rebind(self):
        gw, cur = _make_gw()

        gw.bind_chat(12345, "admin_dm")

        sql, params = cur.execute.call_args[0]
        assert "INSERT INTO environment_bindings" in sql
        assert "ON CONFLICT (chat_id) DO UPDATE" in sql
        assert params == (12345, "admin_dm")

        # Rebind same chat_id to different environment
        gw.bind_chat(12345, "editorial_group")

        sql, params = cur.execute.call_args[0]
        assert params == (12345, "editorial_group")

    def test_unbind_chat(self):
        gw, cur = _make_gw()

        gw.unbind_chat(12345)

        sql, params = cur.execute.call_args[0]
        assert "DELETE FROM environment_bindings" in sql
        assert params == (12345,)


# ===================================================================
#  list_environments
# ===================================================================

class TestListEnvironments:

    def test_list_environments(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = [
            ("admin_dm", "Admin chat", "Full access.", None, "2026-01-01", "2026-01-01"),
            ("editorial_group", "Editorial", "Group context.", ["tech_support"], "2026-01-01", "2026-01-01"),
        ]

        result = gw.list_environments()

        assert len(result) == 2
        assert result[0]["name"] == "admin_dm"
        assert result[0]["allowed_domains"] is None
        assert result[1]["name"] == "editorial_group"
        assert result[1]["allowed_domains"] == ["tech_support"]
        sql = cur.execute.call_args[0][0]
        assert "FROM environments ORDER BY name" in sql

    def test_list_environments_empty(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = []

        result = gw.list_environments()

        assert result == []


# ===================================================================
#  update_environment
# ===================================================================

class TestUpdateEnvironment:

    def test_update_environment_partial_fields(self):
        gw, cur = _make_gw()
        cur.rowcount = 1

        result = gw.update_environment("admin_dm", description="New description")

        assert result is True
        sql, params = cur.execute.call_args[0]
        assert "UPDATE environments SET" in sql
        assert "description = %s" in sql
        assert "updated_at = NOW()" in sql
        assert params == ("New description", "admin_dm")

    def test_update_multiple_fields(self):
        gw, cur = _make_gw()
        cur.rowcount = 1

        result = gw.update_environment(
            "admin_dm",
            description="Updated",
            system_context="New context",
            allowed_domains=["payments"],
        )

        assert result is True
        sql, params = cur.execute.call_args[0]
        assert "description = %s" in sql
        assert "system_context = %s" in sql
        assert "allowed_domains = %s" in sql
        # Last param is always the name for WHERE clause
        assert params[-1] == "admin_dm"

    def test_update_returns_false_when_not_found(self):
        gw, cur = _make_gw()
        cur.rowcount = 0

        result = gw.update_environment("nonexistent", description="x")

        assert result is False

    def test_update_ignores_unknown_fields(self):
        gw, cur = _make_gw()

        result = gw.update_environment("admin_dm", bogus_field="value")

        assert result is False
        cur.execute.assert_not_called()
