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
#  log_payment_validation
# ===================================================================

class TestLogPaymentValidation:

    def test_inserts_and_returns_id(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = ("val-1",)

        result = gw.log_payment_validation(
            contractor_id="c-100",
            contractor_type="individual",
            input_text="invoice text",
            parsed_json='{"amount": 1000}',
        )

        assert result == "val-1"
        sql, params = cur.execute.call_args[0]
        assert "INSERT INTO payment_validations" in sql
        assert "RETURNING id" in sql
        assert params == ("c-100", "individual", "invoice text", '{"amount": 1000}', [], False)

    def test_warnings_and_is_final_passed(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = ("val-2",)

        gw.log_payment_validation(
            contractor_id="c-200",
            contractor_type="company",
            input_text="text",
            parsed_json="{}",
            warnings=["missing INN", "bad date"],
            is_final=True,
        )

        _, params = cur.execute.call_args[0]
        assert params == ("c-200", "company", "text", "{}", ["missing INN", "bad date"], True)


# ===================================================================
#  finalize_payment_validation
# ===================================================================

class TestFinalizePaymentValidation:

    def test_updates_is_final(self):
        gw, cur = _make_gw()

        gw.finalize_payment_validation("val-1")

        sql, params = cur.execute.call_args[0]
        assert "UPDATE payment_validations SET is_final = TRUE" in sql
        assert params == ("val-1",)

    def test_returns_none(self):
        gw, cur = _make_gw()

        result = gw.finalize_payment_validation("val-1")

        assert result is None
