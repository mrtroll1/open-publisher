"""Budget sheet repository — read/write monthly payment sheets."""

from __future__ import annotations

import logging

from common.config import BUDGET_SHEETS_FOLDER_ID, BUDGET_TEMPLATE_SHEET_ID, EUR_RUB_CELL
from common.models import Contractor, Currency
from backend.infrastructure.gateways.drive_gateway import DriveGateway
from backend.infrastructure.gateways.sheets_gateway import SheetsGateway
from backend.infrastructure.repositories.sheets_utils import parse_int

logger = logging.getLogger(__name__)

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


def redirect_in_budget(source_name: str, target: Contractor, month: str) -> None:
    """Move a source author's amount into the target contractor's row in the budget sheet."""
    sheet_id = _find_sheet(month)
    if not sheet_id:
        return
    rows = _sheets.read(sheet_id, "A2:E200")

    source_lower = source_name.lower().strip()
    target_lower = target.display_name.lower().strip()
    source_idx = None
    target_idx = None
    source_amount = 0

    for i, row in enumerate(rows):
        if not row or not row[0].strip():
            continue
        name = row[0].strip().lower()
        if name == source_lower:
            source_idx = i
            eur = parse_int(row[2]) if len(row) > 2 else 0
            rub = parse_int(row[3]) if len(row) > 3 else 0
            source_amount = eur if target.currency == Currency.EUR else rub
        if name == target_lower:
            target_idx = i

    if source_idx is None or target_idx is None or not source_amount:
        logger.warning("redirect_in_budget: source=%s(%s) target=%s(%s) — skipping",
                        source_name, source_idx, target.display_name, target_idx)
        return

    # Update target row: add amount + append to note
    t_row = rows[target_idx] + [""] * (5 - len(rows[target_idx]))
    old_eur = parse_int(t_row[2])
    old_rub = parse_int(t_row[3])
    old_note = t_row[4].strip()

    if target.currency == Currency.EUR:
        t_row[2] = str(old_eur + source_amount)
    else:
        t_row[3] = str(old_rub + source_amount)

    bonus_entry = f"{source_name} ({source_amount})"
    t_row[4] = f"{old_note}, {bonus_entry}" if old_note else bonus_entry

    t_sheet_row = target_idx + 2  # +1 header, +1 for 1-based
    _sheets.write(sheet_id, f"A{t_sheet_row}:E{t_sheet_row}", [t_row[:5]])

    # Clear source row
    s_sheet_row = source_idx + 2
    _sheets.clear(sheet_id, f"A{s_sheet_row}:E{s_sheet_row}")
    logger.info("Budget: moved %s (%d) → %s", source_name, source_amount, target.display_name)


def unredirect_in_budget(source_name: str, target: Contractor, month: str) -> None:
    """Remove a source author from the target's row and restore as standalone."""
    sheet_id = _find_sheet(month)
    if not sheet_id:
        return
    rows = _sheets.read(sheet_id, "A2:E200")

    target_lower = target.display_name.lower().strip()
    target_idx = None
    for i, row in enumerate(rows):
        if not row or not row[0].strip():
            continue
        if row[0].strip().lower() == target_lower:
            target_idx = i
            break

    if target_idx is None:
        return

    t_row = rows[target_idx] + [""] * (5 - len(rows[target_idx]))
    old_note = t_row[4].strip()
    if not old_note:
        return

    # Parse the bonus for this source from the note
    source_amount = 0
    new_parts = []
    for part in old_note.split(","):
        part = part.strip()
        if "(" not in part or ")" not in part:
            new_parts.append(part)
            continue
        idx_open = part.rfind("(")
        idx_close = part.rfind(")")
        name = part[:idx_open].strip()
        if name.lower() == source_name.lower().strip():
            try:
                source_amount = int(part[idx_open + 1:idx_close].strip())
            except ValueError:
                new_parts.append(part)
            continue
        new_parts.append(part)

    if not source_amount:
        return

    # Subtract from target total
    old_eur = parse_int(t_row[2])
    old_rub = parse_int(t_row[3])
    if target.currency == Currency.EUR:
        t_row[2] = str(old_eur - source_amount)
    else:
        t_row[3] = str(old_rub - source_amount)
    t_row[4] = ", ".join(p for p in new_parts if p)

    t_sheet_row = target_idx + 2
    _sheets.write(sheet_id, f"A{t_sheet_row}:E{t_sheet_row}", [t_row[:5]])

    # Append the source as a standalone row at the bottom
    sym_col = 2 if target.currency == Currency.EUR else 3
    new_row = [""] * 5
    new_row[0] = source_name
    new_row[sym_col] = str(source_amount)
    _sheets.append(sheet_id, "A2:E200", [new_row])
    logger.info("Budget: restored %s (%d) from %s", source_name, source_amount, target.display_name)


def sheet_url(sheet_id: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}"
