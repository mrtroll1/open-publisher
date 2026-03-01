"""Invoice CRUD against the 'invoices' tab in the contractors Google Sheet."""

from __future__ import annotations

import logging
from decimal import Decimal

from common.config import CONTRACTORS_SHEET_ID
from common.models import Currency, Invoice, InvoiceStatus
from backend.infrastructure.gateways.sheets_gateway import SheetsGateway
from backend.infrastructure.repositories.sheets_utils import index_to_column_letter

logger = logging.getLogger(__name__)

_sheets = SheetsGateway()

SHEET_NAME = "invoices"
SHEET_RANGE = f"'{SHEET_NAME}'!A:Z"

COLUMNS = [
    "contractor_id",
    "invoice_number",
    "month",
    "amount",
    "currency",
    "article_ids",
    "status",
    "gdrive_path",
    "doc_id",
    "legium_link",
]


def _row_to_invoice(row: dict[str, str]) -> Invoice | None:
    try:
        article_ids_raw = row.get("article_ids", "")
        article_ids = [a.strip() for a in article_ids_raw.split(",") if a.strip()]
        inv_num = int(row.get("invoice_number", "0") or "0")
        return Invoice(
            contractor_id=row.get("contractor_id", ""),
            invoice_number=inv_num,
            month=row.get("month", ""),
            amount=Decimal(row.get("amount", "0") or "0"),
            currency=Currency(row.get("currency", "EUR")),
            article_ids=article_ids,
            status=InvoiceStatus(row.get("status", "draft")),
            gdrive_path=row.get("gdrive_path", ""),
            doc_id=row.get("doc_id", ""),
            legium_link=row.get("legium_link", ""),
        )
    except Exception as e:
        logger.warning("Skipping invoice row: %s", e)
        return None


def _invoice_to_row(inv: Invoice) -> list[str]:
    return [
        inv.contractor_id,
        str(inv.invoice_number),
        inv.month,
        str(inv.amount),
        inv.currency.value,
        ",".join(inv.article_ids),
        inv.status.value,
        inv.gdrive_path,
        inv.doc_id,
        inv.legium_link,
    ]


def load_invoices(month: str) -> list[Invoice]:
    """Load all invoices for a given month."""
    rows = _sheets.read_as_dicts(CONTRACTORS_SHEET_ID, SHEET_RANGE)
    invoices = []
    for r in rows:
        if r.get("month") == month:
            inv = _row_to_invoice(r)
            if inv:
                invoices.append(inv)
    return invoices


def save_invoice(invoice: Invoice) -> None:
    """Append a new invoice row."""
    _sheets.append(CONTRACTORS_SHEET_ID, SHEET_RANGE, [_invoice_to_row(invoice)])
    logger.info("Saved invoice for %s (%s)", invoice.contractor_id, invoice.month)


def _find_invoice_row(contractor_id: str, month: str) -> tuple[list[str], int] | None:
    """Find invoice row by contractor_id + month. Returns (headers, row_index) or None."""
    rows = _sheets.read(CONTRACTORS_SHEET_ID, SHEET_RANGE)
    if not rows:
        return None
    headers = [h.strip().lower() for h in rows[0]]
    try:
        cid_col = headers.index("contractor_id")
        month_col = headers.index("month")
    except ValueError:
        logger.error("Required columns not found in invoices sheet")
        return None
    for idx, row in enumerate(rows[1:], start=1):
        padded = row + [""] * (len(headers) - len(row))
        if padded[cid_col] == contractor_id and padded[month_col] == month:
            return headers, idx
    return None


def _write_invoice_field(headers: list[str], row_idx: int, field: str, value: str) -> bool:
    """Find column by name and write value to the invoice row. Returns True on success."""
    try:
        col_idx = headers.index(field)
    except ValueError:
        logger.error("Column %s not found in invoices sheet", field)
        return False
    col_letter = index_to_column_letter(col_idx)
    _sheets.write(CONTRACTORS_SHEET_ID, f"'{SHEET_NAME}'!{col_letter}{row_idx + 1}", [[value]])
    return True


def update_invoice_status(contractor_id: str, month: str, status: InvoiceStatus) -> None:
    result = _find_invoice_row(contractor_id, month)
    if result is None:
        logger.warning("Invoice not found for %s/%s", contractor_id, month)
        return
    headers, row_idx = result
    _write_invoice_field(headers, row_idx, "status", status.value)
    logger.info("Updated invoice status for %s/%s to %s", contractor_id, month, status.value)


def update_legium_link(contractor_id: str, month: str, url: str) -> None:
    result = _find_invoice_row(contractor_id, month)
    if result is None:
        logger.warning("Invoice not found for %s/%s", contractor_id, month)
        return
    headers, row_idx = result
    _write_invoice_field(headers, row_idx, "status", InvoiceStatus.SENT.value)
    _write_invoice_field(headers, row_idx, "legium_link", url)
    logger.info("Set legium_link for %s/%s", contractor_id, month)
