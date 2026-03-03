import pytest
from decimal import Decimal

from backend.infrastructure.repositories.sheets.invoice_repo import (
    _invoice_to_row,
    _row_to_invoice,
)
from common.models import Currency, Invoice, InvoiceStatus


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _minimal_row(**overrides) -> dict[str, str]:
    """Build a minimal valid invoice row dict."""
    row = {
        "contractor_id": "c001",
        "contractor_name": "Alice Smith",
        "invoice_number": "42",
        "month": "2026-01",
        "amount": "1500.00",
        "currency": "EUR",
        "article_ids": "art1, art2",
        "status": "draft",
        "gdrive_path": "/invoices/c001",
        "doc_id": "doc_abc",
        "legium_link": "https://legium.io/123",
    }
    row.update(overrides)
    return row


def _minimal_invoice(**overrides) -> Invoice:
    """Build a minimal Invoice model."""
    kwargs = dict(
        contractor_id="c001",
        contractor_name="Alice Smith",
        invoice_number=42,
        month="2026-01",
        amount=Decimal("1500.00"),
        currency=Currency.EUR,
        article_ids=["art1", "art2"],
        status=InvoiceStatus.DRAFT,
        gdrive_path="/invoices/c001",
        doc_id="doc_abc",
        legium_link="https://legium.io/123",
    )
    kwargs.update(overrides)
    return Invoice(**kwargs)


# ===================================================================
#  _row_to_invoice
# ===================================================================

class TestRowToInvoice:

    def test_valid_row(self):
        inv = _row_to_invoice(_minimal_row())
        assert inv is not None
        assert inv.contractor_id == "c001"
        assert inv.invoice_number == 42
        assert inv.month == "2026-01"
        assert inv.amount == Decimal("1500.00")
        assert inv.currency == Currency.EUR
        assert inv.article_ids == ["art1", "art2"]
        assert inv.status == InvoiceStatus.DRAFT
        assert inv.gdrive_path == "/invoices/c001"
        assert inv.doc_id == "doc_abc"
        assert inv.legium_link == "https://legium.io/123"

    def test_empty_article_ids(self):
        inv = _row_to_invoice(_minimal_row(article_ids=""))
        assert inv is not None
        assert inv.article_ids == []

    def test_single_article_id(self):
        inv = _row_to_invoice(_minimal_row(article_ids="art1"))
        assert inv is not None
        assert inv.article_ids == ["art1"]

    def test_article_ids_whitespace_trimmed(self):
        inv = _row_to_invoice(_minimal_row(article_ids=" art1 , art2 , art3 "))
        assert inv is not None
        assert inv.article_ids == ["art1", "art2", "art3"]

    def test_missing_invoice_number_defaults_to_zero(self):
        inv = _row_to_invoice(_minimal_row(invoice_number=""))
        assert inv is not None
        assert inv.invoice_number == 0

    def test_missing_amount_defaults_to_zero(self):
        inv = _row_to_invoice(_minimal_row(amount=""))
        assert inv is not None
        assert inv.amount == Decimal("0")

    def test_status_sent(self):
        inv = _row_to_invoice(_minimal_row(status="sent"))
        assert inv is not None
        assert inv.status == InvoiceStatus.SENT

    def test_status_paid(self):
        inv = _row_to_invoice(_minimal_row(status="paid"))
        assert inv is not None
        assert inv.status == InvoiceStatus.PAID

    def test_currency_rub(self):
        inv = _row_to_invoice(_minimal_row(currency="RUB"))
        assert inv is not None
        assert inv.currency == Currency.RUB

    def test_currency_usd(self):
        inv = _row_to_invoice(_minimal_row(currency="USD"))
        assert inv is not None
        assert inv.currency == Currency.USD

    def test_invalid_currency_returns_none(self):
        inv = _row_to_invoice(_minimal_row(currency="INVALID"))
        assert inv is None

    def test_invalid_status_returns_none(self):
        inv = _row_to_invoice(_minimal_row(status="unknown_status"))
        assert inv is None

    def test_missing_fields_use_defaults(self):
        inv = _row_to_invoice({})
        assert inv is not None
        assert inv.contractor_id == ""
        assert inv.invoice_number == 0
        assert inv.amount == Decimal("0")
        assert inv.gdrive_path == ""

    def test_default_currency_eur(self):
        row = _minimal_row()
        del row["currency"]
        inv = _row_to_invoice(row)
        assert inv is not None
        assert inv.currency == Currency.EUR

    def test_default_status_draft(self):
        row = _minimal_row()
        del row["status"]
        inv = _row_to_invoice(row)
        assert inv is not None
        assert inv.status == InvoiceStatus.DRAFT


# ===================================================================
#  _invoice_to_row
# ===================================================================

class TestInvoiceToRow:

    def test_basic_conversion(self):
        inv = _minimal_invoice()
        row = _invoice_to_row(inv)
        assert row == [
            "c001",           # contractor_id
            "Alice Smith",    # contractor_name
            "42",             # invoice_number
            "2026-01",        # month
            "1500.00",        # amount
            "EUR",            # currency
            "art1,art2",      # article_ids
            "draft",          # status
            "/invoices/c001", # gdrive_path
            "doc_abc",        # doc_id
            "https://legium.io/123",  # legium_link
        ]

    def test_empty_article_ids(self):
        inv = _minimal_invoice(article_ids=[])
        row = _invoice_to_row(inv)
        assert row[6] == ""

    def test_single_article_id(self):
        inv = _minimal_invoice(article_ids=["art1"])
        row = _invoice_to_row(inv)
        assert row[6] == "art1"

    def test_status_values(self):
        for status in InvoiceStatus:
            inv = _minimal_invoice(status=status)
            row = _invoice_to_row(inv)
            assert row[7] == status.value

    def test_currency_values(self):
        for currency in Currency:
            inv = _minimal_invoice(currency=currency)
            row = _invoice_to_row(inv)
            assert row[5] == currency.value

    def test_zero_invoice_number(self):
        inv = _minimal_invoice(invoice_number=0)
        row = _invoice_to_row(inv)
        assert row[2] == "0"

    def test_large_amount(self):
        inv = _minimal_invoice(amount=Decimal("999999.99"))
        row = _invoice_to_row(inv)
        assert row[4] == "999999.99"

    def test_empty_optional_fields(self):
        inv = _minimal_invoice(gdrive_path="", doc_id="", legium_link="")
        row = _invoice_to_row(inv)
        assert row[8] == ""
        assert row[9] == ""
        assert row[10] == ""


# ===================================================================
#  Roundtrip: row → invoice → row
# ===================================================================

class TestRoundtrip:

    def test_row_to_invoice_to_row(self):
        original_row = _minimal_row()
        inv = _row_to_invoice(original_row)
        assert inv is not None
        row_back = _invoice_to_row(inv)
        # article_ids formatting differs: "art1, art2" → ["art1", "art2"] → "art1,art2"
        expected = [
            "c001", "Alice Smith", "42", "2026-01", "1500.00", "EUR",
            "art1,art2", "draft", "/invoices/c001", "doc_abc",
            "https://legium.io/123",
        ]
        assert row_back == expected

    def test_invoice_to_row_to_invoice(self):
        original = _minimal_invoice()
        row = _invoice_to_row(original)
        row_dict = dict(zip(
            ["contractor_id", "contractor_name", "invoice_number", "month", "amount",
             "currency", "article_ids", "status", "gdrive_path", "doc_id", "legium_link"],
            row,
        ))
        inv_back = _row_to_invoice(row_dict)
        assert inv_back is not None
        assert inv_back.contractor_id == original.contractor_id
        assert inv_back.invoice_number == original.invoice_number
        assert inv_back.amount == original.amount
        assert inv_back.currency == original.currency
        assert inv_back.status == original.status
        assert inv_back.article_ids == original.article_ids
