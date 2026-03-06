"""Budget sheet repository — read/write monthly payment sheets."""

from __future__ import annotations

import logging

from common.config import BUDGET_SHEETS_FOLDER_ID, BUDGET_TEMPLATE_SHEET_ID, EUR_RUB_CELL
from common.models import Contractor, Currency
from backend.infrastructure.gateways.drive_gateway import DriveGateway
from backend.infrastructure.gateways.sheets_gateway import SheetsGateway
from backend.infrastructure.repositories.sheets.sheets_utils import parse_int

logger = logging.getLogger(__name__)

EUR_RUB_RATE = 100

_drive = DriveGateway()
_sheets = SheetsGateway()

SHEET_NAME_PREFIX = "Payments-for-"


def _sheet_name(month: str) -> str:
    return f"{SHEET_NAME_PREFIX}{month}"


def _find_sheet(month: str) -> str | None:
    """Find a budget sheet by month. Returns sheet ID or None."""
    return _drive.find_file_by_name(_sheet_name(month), BUDGET_SHEETS_FOLDER_ID)


def read_all_amounts(month: str) -> dict[str, tuple[int, int, str]]:
    """Read all payment entries for a month.

    Returns {name_lower: (eur, rub, note)}.
    """
    sheet_id = _find_sheet(month)
    if not sheet_id:
        return {}
    rows = _sheets.read(sheet_id, "A2:E200")
    amounts = {}
    for row in rows:
        if not row or not row[0].strip():
            continue
        name = row[0].strip().lower()
        eur = parse_int(row[2]) if len(row) > 2 else 0
        rub = parse_int(row[3]) if len(row) > 3 else 0
        note = row[4].strip() if len(row) > 4 else ""
        if eur or rub:
            amounts[name] = (eur, rub, note)
    return amounts


def lookup_amount(contractor: Contractor, month: str) -> int | None:
    """Look up a single contractor's amount from the budget sheet.

    Returns the integer amount in the contractor's currency, or None.
    """
    sheet_id = _find_sheet(month)
    if not sheet_id:
        logger.info("Budget sheet not found: %s", _sheet_name(month))
        return None

    rows = _sheets.read(sheet_id, "A2:D200")
    name_lower = contractor.display_name.lower().strip()
    for row in rows:
        if len(row) >= 1 and row[0].strip().lower() == name_lower:
            eur = parse_int(row[2]) if len(row) > 2 else 0
            rub = parse_int(row[3]) if len(row) > 3 else 0
            amount = eur if contractor.currency == Currency.EUR else rub
            if amount:
                logger.info("Budget lookup for %s: %d", contractor.display_name, amount)
                return amount
    logger.info("Contractor %s not found in budget sheet %s", contractor.display_name, _sheet_name(month))
    return None


def create_sheet(month: str) -> str:
    """Copy the budget template for a given month. Returns the new sheet ID."""
    return _drive.copy_file(
        BUDGET_TEMPLATE_SHEET_ID, _sheet_name(month), BUDGET_SHEETS_FOLDER_ID,
    )


def populate_sheet(sheet_id: str, rows: list[list[str]], header_label: str) -> None:
    """Write payment rows and header to a budget sheet."""
    _sheets.clear(sheet_id, "A2:E200")
    _sheets.clear(sheet_id, "G6")
    _sheets.write(sheet_id, "H1", [[header_label]])
    if rows:
        end_row = 1 + len(rows)
        _sheets.write(sheet_id, f"A2:E{end_row}", rows)


def write_pnl_section(sheet_id: str, start_row: int, eur_rub_rate: float, pnl_rows: list[list[str]]) -> None:
    if eur_rub_rate:
        _sheets.write(sheet_id, EUR_RUB_CELL, [[eur_rub_rate]])
    if pnl_rows:
        end_row = start_row + len(pnl_rows) - 1
        _sheets.write(sheet_id, f"A{start_row}:E{end_row}", pnl_rows)


from backend.commands.budget.redirect import redirect_in_budget, unredirect_in_budget  # noqa: F401


def sheet_url(sheet_id: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}"
