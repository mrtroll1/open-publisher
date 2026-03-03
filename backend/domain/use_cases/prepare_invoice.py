"""Helpers for preparing already-generated invoices for delivery."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from common.models import Contractor, Invoice
from backend.infrastructure.gateways.docs_gateway import DocsGateway
from backend.infrastructure.repositories.invoice_repo import load_invoices

logger = logging.getLogger(__name__)


@dataclass
class PreparedInvoice:
    pdf_bytes: bytes
    invoice: Invoice
    contractor: Contractor


def prepare_existing_invoice(contractor: Contractor, month: str) -> PreparedInvoice | None:
    """Load a previously generated invoice and export its PDF.

    Returns None if no invoice exists or PDF export fails.
    """
    invoices = load_invoices(month)
    inv = next((i for i in invoices if i.contractor_id == contractor.id), None)
    if not inv or not inv.doc_id:
        return None

    try:
        pdf_bytes = DocsGateway().export_pdf(inv.doc_id)
    except Exception as e:
        logger.error("Failed to export PDF for %s: %s", contractor.display_name, e)
        return None

    return PreparedInvoice(pdf_bytes=pdf_bytes, invoice=inv, contractor=contractor)
