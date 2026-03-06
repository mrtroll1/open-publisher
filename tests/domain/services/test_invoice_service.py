"""Tests for backend/domain/services/invoice_service.py."""

from unittest.mock import MagicMock, patch

from common.models import Currency, InvoiceStatus


# ===================================================================
#  resolve_existing_invoice — mock prepare_existing_invoice
# ===================================================================

class TestResolveExistingInvoice:

    def _make_contractor(self, currency=Currency.RUB):
        c = MagicMock()
        c.currency = currency
        return c

    def _make_prepared(self, status=InvoiceStatus.DRAFT, legium_link=""):
        prepared = MagicMock()
        prepared.invoice.status = status
        prepared.invoice.legium_link = legium_link
        return prepared

    @patch("backend.commands.invoice.service.prepare_existing_invoice")
    def test_no_invoice_returns_none(self, mock_prep):
        from backend.commands.invoice.service import resolve_existing_invoice
        mock_prep.return_value = None
        result = resolve_existing_invoice(self._make_contractor(), "2026-02")
        assert result is None

    @patch("backend.commands.invoice.service.prepare_existing_invoice")
    def test_eur_draft_sends_proforma(self, mock_prep):
        from backend.commands.invoice.service import (
            DeliveryAction, resolve_existing_invoice,
        )
        mock_prep.return_value = self._make_prepared(InvoiceStatus.DRAFT)
        result = resolve_existing_invoice(self._make_contractor(Currency.EUR), "2026-02")
        assert result is not None
        assert result.action == DeliveryAction.SEND_PROFORMA

    @patch("backend.commands.invoice.service.prepare_existing_invoice")
    def test_eur_sent_already_sent(self, mock_prep):
        from backend.commands.invoice.service import (
            DeliveryAction, resolve_existing_invoice,
        )
        mock_prep.return_value = self._make_prepared(InvoiceStatus.SENT)
        result = resolve_existing_invoice(self._make_contractor(Currency.EUR), "2026-02")
        assert result is not None
        assert result.action == DeliveryAction.PROFORMA_ALREADY_SENT

    @patch("backend.commands.invoice.service.prepare_existing_invoice")
    def test_rub_with_legium_link(self, mock_prep):
        from backend.commands.invoice.service import (
            DeliveryAction, resolve_existing_invoice,
        )
        mock_prep.return_value = self._make_prepared(InvoiceStatus.DRAFT, legium_link="https://legium.io/123")
        result = resolve_existing_invoice(self._make_contractor(Currency.RUB), "2026-02")
        assert result is not None
        assert result.action == DeliveryAction.SEND_RUB_WITH_LEGIUM

    @patch("backend.commands.invoice.service.prepare_existing_invoice")
    def test_rub_draft_no_legium(self, mock_prep):
        from backend.commands.invoice.service import (
            DeliveryAction, resolve_existing_invoice,
        )
        mock_prep.return_value = self._make_prepared(InvoiceStatus.DRAFT, legium_link="")
        result = resolve_existing_invoice(self._make_contractor(Currency.RUB), "2026-02")
        assert result is not None
        assert result.action == DeliveryAction.SEND_RUB_DRAFT

    @patch("backend.commands.invoice.service.prepare_existing_invoice")
    def test_rub_already_sent(self, mock_prep):
        from backend.commands.invoice.service import (
            DeliveryAction, resolve_existing_invoice,
        )
        mock_prep.return_value = self._make_prepared(InvoiceStatus.SENT, legium_link="")
        result = resolve_existing_invoice(self._make_contractor(Currency.RUB), "2026-02")
        assert result is not None
        assert result.action == DeliveryAction.RUB_ALREADY_SENT

    @patch("backend.commands.invoice.service.prepare_existing_invoice")
    def test_result_contains_prepared(self, mock_prep):
        from backend.commands.invoice.service import resolve_existing_invoice
        prepared = self._make_prepared(InvoiceStatus.DRAFT)
        mock_prep.return_value = prepared
        result = resolve_existing_invoice(self._make_contractor(Currency.EUR), "2026-02")
        assert result.prepared is prepared


# ===================================================================
#  prepare_new_invoice_data — mock budget/articles/amount
# ===================================================================

class TestPrepareNewInvoiceData:

    @patch("backend.commands.invoice.service.resolve_amount")
    @patch("backend.commands.invoice.service.fetch_articles")
    @patch("backend.commands.invoice.service.read_budget_amounts")
    def test_returns_data_when_amount_exists(self, mock_budget, mock_articles, mock_resolve):
        from backend.commands.invoice.service import prepare_new_invoice_data

        mock_budget.return_value = {"test": (0, 5000, "")}
        art1 = MagicMock()
        art1.article_id = "art-1"
        art2 = MagicMock()
        art2.article_id = "art-2"
        mock_articles.return_value = [art1, art2]
        mock_resolve.return_value = (5000, "бюджет: 5000₽")

        contractor = MagicMock()
        result = prepare_new_invoice_data(contractor, "2026-02")

        assert result is not None
        assert result.default_amount == 5000
        assert result.explanation == "бюджет: 5000₽"
        assert result.article_ids == ["art-1", "art-2"]
        assert result.num_articles == 2
        assert "2" in result.pub_word

    @patch("backend.commands.invoice.service.resolve_amount")
    @patch("backend.commands.invoice.service.fetch_articles")
    @patch("backend.commands.invoice.service.read_budget_amounts")
    def test_returns_none_when_no_amount(self, mock_budget, mock_articles, mock_resolve):
        from backend.commands.invoice.service import prepare_new_invoice_data

        mock_budget.return_value = {}
        mock_articles.return_value = []
        mock_resolve.return_value = (0, "")

        contractor = MagicMock()
        result = prepare_new_invoice_data(contractor, "2026-02")

        assert result is None

    @patch("backend.commands.invoice.service.resolve_amount")
    @patch("backend.commands.invoice.service.fetch_articles")
    @patch("backend.commands.invoice.service.read_budget_amounts")
    def test_zero_articles_pub_word(self, mock_budget, mock_articles, mock_resolve):
        from backend.commands.invoice.service import prepare_new_invoice_data

        mock_budget.return_value = {"test": (0, 3000, "")}
        mock_articles.return_value = []
        mock_resolve.return_value = (3000, "fixed")

        contractor = MagicMock()
        result = prepare_new_invoice_data(contractor, "2026-02")

        assert result is not None
        assert result.pub_word == "0 публикаций"
        assert result.article_ids == []

    @patch("backend.commands.invoice.service.resolve_amount")
    @patch("backend.commands.invoice.service.fetch_articles")
    @patch("backend.commands.invoice.service.read_budget_amounts")
    def test_single_article_pub_word(self, mock_budget, mock_articles, mock_resolve):
        from backend.commands.invoice.service import prepare_new_invoice_data

        mock_budget.return_value = {}
        art = MagicMock()
        art.article_id = "a1"
        mock_articles.return_value = [art]
        mock_resolve.return_value = (1000, "rate")

        contractor = MagicMock()
        result = prepare_new_invoice_data(contractor, "2026-02")

        assert result is not None
        assert "1 публикация" == result.pub_word
