from decimal import Decimal
from unittest.mock import MagicMock, patch

from backend.commands.invoice.prepare import PreparedInvoice, prepare_existing_invoice
from common.models import (
    Currency,
    GlobalContractor,
    Invoice,
    InvoiceStatus,
)


# ---------------------------------------------------------------------------
#  Factories
# ---------------------------------------------------------------------------

def _global(**overrides) -> GlobalContractor:
    kwargs = dict(
        id="g1", name_en="Test Global", address="Addr", email="a@b.c",
        bank_name="Bank", bank_account="ACC", swift="SWIFT",
    )
    kwargs.update(overrides)
    return GlobalContractor(**kwargs)


def _invoice(**overrides) -> Invoice:
    kwargs = dict(
        contractor_id="g1", contractor_name="Test Global",
        invoice_number=1, month="2026-01",
        amount=Decimal("500"), currency=Currency.EUR,
        doc_id="doc_abc",
    )
    kwargs.update(overrides)
    return Invoice(**kwargs)


# ---------------------------------------------------------------------------
#  Patch paths
# ---------------------------------------------------------------------------

_PATCH_LOAD = "backend.commands.invoice.prepare.load_invoices"
_PATCH_DOCS = "backend.commands.invoice.prepare.DocsGateway"


# ===================================================================
#  Success path
# ===================================================================

class TestPrepareExistingInvoice:

    def test_found_invoice_with_doc_id(self):
        inv = _invoice(doc_id="doc_abc")
        contractor = _global()

        with patch(_PATCH_LOAD, return_value=[inv]), \
             patch(_PATCH_DOCS) as MockDocs:
            MockDocs.return_value.export_pdf.return_value = b"%PDF-data"
            result = prepare_existing_invoice(contractor, "2026-01")

        assert result is not None
        assert isinstance(result, PreparedInvoice)
        assert result.pdf_bytes == b"%PDF-data"
        assert result.invoice is inv
        assert result.contractor is contractor
        MockDocs.return_value.export_pdf.assert_called_once_with("doc_abc")

    def test_invoice_not_found(self):
        contractor = _global(id="g1")

        with patch(_PATCH_LOAD, return_value=[]), \
             patch(_PATCH_DOCS) as MockDocs:
            result = prepare_existing_invoice(contractor, "2026-01")

        assert result is None
        MockDocs.return_value.export_pdf.assert_not_called()

    def test_invoice_found_but_no_doc_id(self):
        inv = _invoice(doc_id="")
        contractor = _global()

        with patch(_PATCH_LOAD, return_value=[inv]), \
             patch(_PATCH_DOCS) as MockDocs:
            result = prepare_existing_invoice(contractor, "2026-01")

        assert result is None
        MockDocs.return_value.export_pdf.assert_not_called()

    def test_pdf_export_fails(self):
        inv = _invoice(doc_id="doc_abc")
        contractor = _global()

        with patch(_PATCH_LOAD, return_value=[inv]), \
             patch(_PATCH_DOCS) as MockDocs:
            MockDocs.return_value.export_pdf.side_effect = RuntimeError("API error")
            result = prepare_existing_invoice(contractor, "2026-01")

        assert result is None

    def test_matches_correct_contractor_id(self):
        inv_other = _invoice(contractor_id="g2", doc_id="doc_other")
        inv_match = _invoice(contractor_id="g1", doc_id="doc_match")
        contractor = _global(id="g1")

        with patch(_PATCH_LOAD, return_value=[inv_other, inv_match]), \
             patch(_PATCH_DOCS) as MockDocs:
            MockDocs.return_value.export_pdf.return_value = b"%PDF"
            result = prepare_existing_invoice(contractor, "2026-01")

        assert result is not None
        assert result.invoice.doc_id == "doc_match"
        MockDocs.return_value.export_pdf.assert_called_once_with("doc_match")

    def test_multiple_invoices_returns_first_match(self):
        inv1 = _invoice(contractor_id="g1", doc_id="doc_first")
        inv2 = _invoice(contractor_id="g1", doc_id="doc_second")
        contractor = _global(id="g1")

        with patch(_PATCH_LOAD, return_value=[inv1, inv2]), \
             patch(_PATCH_DOCS) as MockDocs:
            MockDocs.return_value.export_pdf.return_value = b"%PDF"
            result = prepare_existing_invoice(contractor, "2026-01")

        assert result is not None
        assert result.invoice.doc_id == "doc_first"
