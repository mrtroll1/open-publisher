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
#  create_code_task
# ===================================================================

class TestCreateCodeTask:

    def test_inserts_and_returns_id(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = ("abc-123",)

        result = gw.create_code_task(
            requested_by="admin",
            input_text="write a parser",
            output_text="def parse(): ...",
        )

        assert result == "abc-123"
        sql, params = cur.execute.call_args[0]
        assert "INSERT INTO code_tasks" in sql
        assert "RETURNING id" in sql
        assert params == ("admin", "write a parser", "def parse(): ...", False)

    def test_verbose_flag_passed(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = ("xyz",)

        gw.create_code_task(
            requested_by="user",
            input_text="in",
            output_text="out",
            verbose=True,
        )

        _, params = cur.execute.call_args[0]
        assert params == ("user", "in", "out", True)


# ===================================================================
#  rate_code_task
# ===================================================================

class TestRateCodeTask:

    def test_updates_rating(self):
        gw, cur = _make_gw()

        gw.rate_code_task(task_id="abc-123", rating=5)

        sql, params = cur.execute.call_args[0]
        assert "UPDATE code_tasks SET rating" in sql
        assert "rated_at = NOW()" in sql
        assert params == (5, "abc-123")

    def test_returns_none(self):
        gw, cur = _make_gw()

        result = gw.rate_code_task(task_id="abc", rating=1)

        assert result is None
