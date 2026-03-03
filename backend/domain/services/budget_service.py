"""Budget orchestration — redirect/unredirect operations on budget sheets."""

from __future__ import annotations

import logging

from common.models import Contractor, Currency
from backend.infrastructure.gateways.drive_gateway import DriveGateway
from backend.infrastructure.gateways.sheets_gateway import SheetsGateway
from backend.infrastructure.repositories.sheets.budget_repo import (
    EUR_RUB_RATE,
    _find_sheet,
)
from backend.infrastructure.repositories.sheets.sheets_utils import parse_int

logger = logging.getLogger(__name__)

_drive = DriveGateway()
_sheets = SheetsGateway()


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
    source_eur = 0
    source_rub = 0

    for i, row in enumerate(rows):
        if not row or not row[0].strip():
            continue
        name = row[0].strip().lower()
        if name == source_lower:
            source_idx = i
            source_eur = parse_int(row[2]) if len(row) > 2 else 0
            source_rub = parse_int(row[3]) if len(row) > 3 else 0
        if name == target_lower:
            target_idx = i

    if source_idx is None or target_idx is None or not (source_eur or source_rub):
        logger.warning("redirect_in_budget: source=%s(%s) target=%s(%s) — skipping",
                        source_name, source_idx, target.display_name, target_idx)
        return

    # Determine amount to add, converting if currencies differ
    if target.currency == Currency.EUR:
        add_amount = source_eur or (source_rub // EUR_RUB_RATE if source_rub else 0)
    else:
        add_amount = source_rub or (source_eur * EUR_RUB_RATE if source_eur else 0)

    if not add_amount:
        return

    # Update target row: add amount + append to note
    t_row = rows[target_idx] + [""] * (5 - len(rows[target_idx]))
    old_eur = parse_int(t_row[2])
    old_rub = parse_int(t_row[3])
    old_note = t_row[4].strip()

    if target.currency == Currency.EUR:
        t_row[2] = str(old_eur + add_amount)
    else:
        t_row[3] = str(old_rub + add_amount)

    bonus_entry = f"{source_name} ({add_amount})"
    t_row[4] = f"{old_note}, {bonus_entry}" if old_note else bonus_entry

    t_sheet_row = target_idx + 2  # +1 header, +1 for 1-based
    _sheets.write(sheet_id, f"A{t_sheet_row}:E{t_sheet_row}", [t_row[:5]])

    # Clear source row
    s_sheet_row = source_idx + 2
    _sheets.clear(sheet_id, f"A{s_sheet_row}:E{s_sheet_row}")
    logger.info("Budget: moved %s (%d) → %s", source_name, add_amount, target.display_name)


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

    # Parse the bonus for this source from the note: "name (amount)"
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

    # Restore source as a standalone row in the first empty slot
    # Amount stays in target's currency (the converted value)
    sym_col = 2 if target.currency == Currency.EUR else 3
    new_row = [""] * 5
    new_row[0] = source_name
    new_row[sym_col] = str(source_amount)
    empty_idx = len(rows)
    for i, row in enumerate(rows):
        if not row or not row[0].strip():
            empty_idx = i
            break
    write_row = empty_idx + 2  # +1 header, +1 for 1-based
    _sheets.write(sheet_id, f"A{write_row}:E{write_row}", [new_row])
    logger.info("Budget: restored %s (%d) from %s", source_name, source_amount, target.display_name)
