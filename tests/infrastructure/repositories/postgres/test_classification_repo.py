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
#  log_classification
# ===================================================================

class TestLogClassification:

    def test_inserts_into_llm_classifications(self):
        gw, cur = _make_gw()

        gw.log_classification(
            task="routing",
            model="gemini-2.0-flash",
            input_text="hello",
            output_json='{"intent": "greeting"}',
            latency_ms=120,
        )

        sql, params = cur.execute.call_args[0]
        assert "INSERT INTO llm_classifications" in sql
        assert params == ("routing", "gemini-2.0-flash", "hello", '{"intent": "greeting"}', 120)

    def test_returns_none(self):
        gw, cur = _make_gw()

        result = gw.log_classification(
            task="classify",
            model="gemini",
            input_text="x",
            output_json="{}",
            latency_ms=0,
        )

        assert result is None
