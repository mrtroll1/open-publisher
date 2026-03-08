"""Tests for InvoiceService."""

from unittest.mock import MagicMock, patch

from backend.commands.invoice.service import (
    DeliveryAction,
    InvoiceService,
)
from backend.models import Currency, InvoiceStatus


class TestFolderPath:
    def test_global_contractor(self):
        c = MagicMock(spec=["name_en"])
        c.name_en = "John Doe"
        # Make isinstance check work for GlobalContractor
        with patch("backend.commands.invoice.service.isinstance", side_effect=lambda obj, cls: True):
            _parent, month, name = InvoiceService().folder_path(c, "2025-01")
        assert name == "JohnDoe"
        assert month == "2025-01"

    def test_domestic_contractor(self):
        c = MagicMock()
        c.display_name = "Иван Петров"
        svc = InvoiceService()
        with patch("backend.commands.invoice.service.isinstance", return_value=False):
            _, month_folder, name = svc.folder_path(c, "2025-01")
        assert month_folder == "01-2025"
        assert name == "ИванПетров"


class TestResolveExisting:
    @patch("backend.commands.invoice.service.prepare_existing_invoice", return_value=None)
    def test_returns_none_when_no_invoice(self, _):
        result = InvoiceService().resolve_existing(MagicMock(), "2025-01")
        assert result is None

    @patch("backend.commands.invoice.service.prepare_existing_invoice")
    def test_draft_eur_returns_send_proforma(self, mock_prepare):
        inv = MagicMock(status=InvoiceStatus.DRAFT, legium_link=None)
        mock_prepare.return_value = MagicMock(invoice=inv)
        contractor = MagicMock(currency=Currency.EUR)

        result = InvoiceService().resolve_existing(contractor, "2025-01")

        assert result is not None
        assert result.action == DeliveryAction.SEND_PROFORMA

    @patch("backend.commands.invoice.service.prepare_existing_invoice")
    def test_rub_with_legium(self, mock_prepare):
        inv = MagicMock(status=InvoiceStatus.DRAFT, legium_link="https://legium.test")
        mock_prepare.return_value = MagicMock(invoice=inv)
        contractor = MagicMock(currency=Currency.RUB)

        result = InvoiceService().resolve_existing(contractor, "2025-01")

        assert result.action == DeliveryAction.SEND_RUB_WITH_LEGIUM


class TestPrepareNewData:
    @patch("backend.commands.invoice.service.RepublicGateway")
    @patch("backend.commands.invoice.service.load_all_amounts", return_value={})
    @patch("backend.commands.invoice.service.resolve_amount", return_value=(0, ""))
    def test_returns_none_when_no_budget(self, *_):
        result = InvoiceService().prepare_new_data(MagicMock(), "2025-01")
        assert result is None

    @patch("backend.commands.invoice.service.RepublicGateway")
    @patch("backend.commands.invoice.service.load_all_amounts")
    @patch("backend.commands.invoice.service.resolve_amount", return_value=(1000, "1000 за 3 публикации"))
    def test_returns_data_when_budget_exists(self, _resolve, _budget, mock_gw_cls):
        mock_gw_cls.return_value.fetch_articles.return_value = [
            MagicMock(article_id="a1"), MagicMock(article_id="a2"),
        ]
        result = InvoiceService().prepare_new_data(MagicMock(), "2025-01")

        assert result is not None
        assert result.default_amount == 1000
        assert result.article_ids == ["a1", "a2"]
        assert result.num_articles == 2
