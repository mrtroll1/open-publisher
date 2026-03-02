"""Tests for backend/infrastructure/gateways/airtable_gateway.py"""

from unittest.mock import MagicMock, patch

import pytest

from common.models import AirtableExpense


def _make_expense(**overrides) -> AirtableExpense:
    defaults = dict(
        payed="2026-01-15",
        amount_rub=10000.0,
        contractor="Иванов",
        unit="editorial",
        entity="Republic",
        description="Гонорар",
        group="authors",
        parent="parent_rec_id",
    )
    defaults.update(overrides)
    return AirtableExpense(**defaults)


# ===================================================================
#  upload_expenses()
# ===================================================================

class TestUploadExpenses:

    @patch("backend.infrastructure.gateways.airtable_gateway.AIRTABLE_TOKEN", "tok_test")
    @patch("backend.infrastructure.gateways.airtable_gateway.AIRTABLE_BASE_ID", "appXYZ")
    @patch("backend.infrastructure.gateways.airtable_gateway.AIRTABLE_TABLE_NAME", "expenses")
    @patch("backend.infrastructure.gateways.airtable_gateway.time.sleep")
    @patch("backend.infrastructure.gateways.airtable_gateway.Api")
    def test_single_expense(self, mock_api_cls, mock_sleep):
        mock_table = MagicMock()
        mock_api_cls.return_value.table.return_value = mock_table

        from backend.infrastructure.gateways.airtable_gateway import AirtableGateway
        gw = AirtableGateway()
        exp = _make_expense()
        count = gw.upload_expenses([exp])

        assert count == 1
        mock_table.batch_create.assert_called_once()
        fields = mock_table.batch_create.call_args[0][0][0]
        assert fields["payed"] == "2026-01-15"
        assert fields["amount rub"] == 10000.0
        assert fields["contractor"] == "Иванов"
        assert fields["parent"] == "parent_rec_id"
        assert "splited" not in fields
        assert "comment" not in fields

    @patch("backend.infrastructure.gateways.airtable_gateway.AIRTABLE_TOKEN", "tok_test")
    @patch("backend.infrastructure.gateways.airtable_gateway.AIRTABLE_BASE_ID", "appXYZ")
    @patch("backend.infrastructure.gateways.airtable_gateway.AIRTABLE_TABLE_NAME", "expenses")
    @patch("backend.infrastructure.gateways.airtable_gateway.time.sleep")
    @patch("backend.infrastructure.gateways.airtable_gateway.Api")
    def test_conditional_fields_included(self, mock_api_cls, mock_sleep):
        mock_table = MagicMock()
        mock_api_cls.return_value.table.return_value = mock_table

        from backend.infrastructure.gateways.airtable_gateway import AirtableGateway
        gw = AirtableGateway()
        exp = _make_expense(splited="50/50", comment="test note")
        gw.upload_expenses([exp])

        fields = mock_table.batch_create.call_args[0][0][0]
        assert fields["splited"] == "50/50"
        assert fields["comment"] == "test note"

    @patch("backend.infrastructure.gateways.airtable_gateway.AIRTABLE_TOKEN", "tok_test")
    @patch("backend.infrastructure.gateways.airtable_gateway.AIRTABLE_BASE_ID", "appXYZ")
    @patch("backend.infrastructure.gateways.airtable_gateway.AIRTABLE_TABLE_NAME", "expenses")
    @patch("backend.infrastructure.gateways.airtable_gateway.time.sleep")
    @patch("backend.infrastructure.gateways.airtable_gateway.Api")
    def test_batches_at_10(self, mock_api_cls, mock_sleep):
        mock_table = MagicMock()
        mock_api_cls.return_value.table.return_value = mock_table

        from backend.infrastructure.gateways.airtable_gateway import AirtableGateway
        gw = AirtableGateway()
        expenses = [_make_expense(contractor=f"C{i}") for i in range(25)]
        count = gw.upload_expenses(expenses)

        assert count == 25
        assert mock_table.batch_create.call_count == 3  # 10 + 10 + 5
        # Check batch sizes
        calls = mock_table.batch_create.call_args_list
        assert len(calls[0][0][0]) == 10
        assert len(calls[1][0][0]) == 10
        assert len(calls[2][0][0]) == 5

    @patch("backend.infrastructure.gateways.airtable_gateway.AIRTABLE_TOKEN", "tok_test")
    @patch("backend.infrastructure.gateways.airtable_gateway.AIRTABLE_BASE_ID", "appXYZ")
    @patch("backend.infrastructure.gateways.airtable_gateway.AIRTABLE_TABLE_NAME", "expenses")
    @patch("backend.infrastructure.gateways.airtable_gateway.time.sleep")
    @patch("backend.infrastructure.gateways.airtable_gateway.Api")
    def test_partial_failure(self, mock_api_cls, mock_sleep):
        mock_table = MagicMock()
        mock_api_cls.return_value.table.return_value = mock_table
        # First batch succeeds, second fails
        mock_table.batch_create.side_effect = [None, Exception("API error"), None]

        from backend.infrastructure.gateways.airtable_gateway import AirtableGateway
        gw = AirtableGateway()
        expenses = [_make_expense() for _ in range(25)]
        count = gw.upload_expenses(expenses)

        assert count == 15  # 10 success + 0 fail + 5 success

    @patch("backend.infrastructure.gateways.airtable_gateway.AIRTABLE_TOKEN", "")
    @patch("backend.infrastructure.gateways.airtable_gateway.AIRTABLE_BASE_ID", "appXYZ")
    def test_no_token_returns_zero(self):
        from backend.infrastructure.gateways.airtable_gateway import AirtableGateway
        gw = AirtableGateway()
        count = gw.upload_expenses([_make_expense()])
        assert count == 0

    @patch("backend.infrastructure.gateways.airtable_gateway.AIRTABLE_TOKEN", "tok_test")
    @patch("backend.infrastructure.gateways.airtable_gateway.AIRTABLE_BASE_ID", "")
    def test_no_base_id_returns_zero(self):
        from backend.infrastructure.gateways.airtable_gateway import AirtableGateway
        gw = AirtableGateway()
        count = gw.upload_expenses([_make_expense()])
        assert count == 0

    @patch("backend.infrastructure.gateways.airtable_gateway.AIRTABLE_TOKEN", "tok_test")
    @patch("backend.infrastructure.gateways.airtable_gateway.AIRTABLE_BASE_ID", "appXYZ")
    @patch("backend.infrastructure.gateways.airtable_gateway.AIRTABLE_TABLE_NAME", "expenses")
    @patch("backend.infrastructure.gateways.airtable_gateway.time.sleep")
    @patch("backend.infrastructure.gateways.airtable_gateway.Api")
    def test_empty_list(self, mock_api_cls, mock_sleep):
        mock_table = MagicMock()
        mock_api_cls.return_value.table.return_value = mock_table

        from backend.infrastructure.gateways.airtable_gateway import AirtableGateway
        gw = AirtableGateway()
        count = gw.upload_expenses([])
        assert count == 0
        mock_table.batch_create.assert_not_called()
