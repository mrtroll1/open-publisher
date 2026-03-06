"""Budget orchestration — redirect/unredirect operations on budget sheets."""

from __future__ import annotations

import logging

from backend.models import Contractor, Currency
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

    source_idx, source_eur, source_rub = _find_source_row(rows, source_name)
    target_idx = _find_row_by_name(rows, target.display_name)

    if source_idx is None or target_idx is None or not (source_eur or source_rub):
        logger.warning("redirect_in_budget: source=%s(%s) target=%s(%s) — skipping",
                        source_name, source_idx, target.display_name, target_idx)
        return

    add_amount = _convert_amount(source_eur, source_rub, target.currency)
    if not add_amount:
        return

    t_row = _pad_row(rows[target_idx])
    _add_amount_to_row(t_row, add_amount, target.currency)
    bonus_entry = f"{source_name} ({add_amount})"
    old_note = t_row[4].strip()
    t_row[4] = f"{old_note}, {bonus_entry}" if old_note else bonus_entry

    _sheets.write(sheet_id, f"A{target_idx + 2}:E{target_idx + 2}", [t_row[:5]])
    _sheets.clear(sheet_id, f"A{source_idx + 2}:E{source_idx + 2}")
    logger.info("Budget: moved %s (%d) → %s", source_name, add_amount, target.display_name)


def unredirect_in_budget(source_name: str, target: Contractor, month: str) -> None:
    """Remove a source author from the target's row and restore as standalone."""
    sheet_id = _find_sheet(month)
    if not sheet_id:
        return
    rows = _sheets.read(sheet_id, "A2:E200")

    target_idx = _find_row_by_name(rows, target.display_name)
    if target_idx is None:
        return

    t_row = _pad_row(rows[target_idx])
    old_note = t_row[4].strip()
    if not old_note:
        return

    source_amount, new_note = _extract_bonus_from_note(old_note, source_name)
    if not source_amount:
        return

    _subtract_amount_from_row(t_row, source_amount, target.currency)
    t_row[4] = new_note
    _sheets.write(sheet_id, f"A{target_idx + 2}:E{target_idx + 2}", [t_row[:5]])

    _restore_source_row(sheet_id, rows, source_name, source_amount, target.currency)
    logger.info("Budget: restored %s (%d) from %s", source_name, source_amount, target.display_name)


# --- private helpers ---


def _find_row_by_name(rows: list[list[str]], display_name: str) -> int | None:
    name_lower = display_name.lower().strip()
    for i, row in enumerate(rows):
        if row and row[0].strip().lower() == name_lower:
            return i
    return None


def _find_source_row(rows: list[list[str]], source_name: str) -> tuple[int | None, int, int]:
    source_lower = source_name.lower().strip()
    for i, row in enumerate(rows):
        if not row or not row[0].strip():
            continue
        if row[0].strip().lower() == source_lower:
            eur = parse_int(row[2]) if len(row) > 2 else 0
            rub = parse_int(row[3]) if len(row) > 3 else 0
            return i, eur, rub
    return None, 0, 0


def _convert_amount(source_eur: int, source_rub: int, target_currency: Currency) -> int:
    if target_currency == Currency.EUR:
        return source_eur or (source_rub // EUR_RUB_RATE if source_rub else 0)
    return source_rub or (source_eur * EUR_RUB_RATE if source_eur else 0)


def _pad_row(row: list[str]) -> list[str]:
    return row + [""] * (5 - len(row))


def _add_amount_to_row(row: list[str], amount: int, currency: Currency) -> None:
    col = 2 if currency == Currency.EUR else 3
    row[col] = str(parse_int(row[col]) + amount)


def _subtract_amount_from_row(row: list[str], amount: int, currency: Currency) -> None:
    col = 2 if currency == Currency.EUR else 3
    row[col] = str(parse_int(row[col]) - amount)


def _extract_bonus_from_note(note: str, source_name: str) -> tuple[int, str]:
    """Parse 'name (amount)' entries from note. Returns (source_amount, cleaned_note)."""
    source_amount = 0
    new_parts = []
    for part in note.split(","):
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
    return source_amount, ", ".join(p for p in new_parts if p)


def _restore_source_row(
    sheet_id: str, rows: list[list[str]], source_name: str,
    amount: int, currency: Currency,
) -> None:
    """Write source back as a standalone row in the first empty slot."""
    col = 2 if currency == Currency.EUR else 3
    new_row = [""] * 5
    new_row[0] = source_name
    new_row[col] = str(amount)
    empty_idx = len(rows)
    for i, row in enumerate(rows):
        if not row or not row[0].strip():
            empty_idx = i
            break
    _sheets.write(sheet_id, f"A{empty_idx + 2}:E{empty_idx + 2}", [new_row])
