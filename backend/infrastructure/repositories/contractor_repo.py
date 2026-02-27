"""Contractor lookup, fuzzy matching, and CRUD against Google Sheets."""

from __future__ import annotations

import logging
import random
from difflib import SequenceMatcher
from typing import Optional

from pydantic import ValidationError

from common.config import CONTRACTORS_SHEET_ID
from common.models import (
    CONTRACTOR_CLASS_BY_TYPE,
    Contractor,
    ContractorType,
    Currency,
    GlobalContractor,
    IPContractor,
    RoleCode,
    SamozanyatyContractor,
)
from backend.infrastructure.gateways.sheets_gateway import SheetsGateway

logger = logging.getLogger(__name__)

_sheets = SheetsGateway()

# Sheet name → (ContractorType, implicit Currency)
SHEET_CONFIG: dict[str, tuple[ContractorType, Currency]] = {
    "global": (ContractorType.GLOBAL, Currency.EUR),
    "ИП": (ContractorType.IP, Currency.RUB),
    "самозанятый": (ContractorType.SAMOZANYATY, Currency.RUB),
}

# Reverse lookup: ContractorType → sheet name
SHEET_NAME_BY_TYPE: dict[ContractorType, str] = {
    v[0]: k for k, v in SHEET_CONFIG.items()
}


def _sheet_range(sheet_name: str) -> str:
    """Build the A1 range for a sheet, quoting names with special chars."""
    return f"'{sheet_name}'!A:Z"


def _parse_contractor(
    row: dict[str, str],
    contractor_type: ContractorType,
) -> Contractor | None:
    """Convert a sheet row dict into the appropriate Contractor subclass."""
    aliases_raw = row.get("aliases", "")
    aliases = [a.strip() for a in aliases_raw.split(",") if a.strip()]

    role_raw = row.get("role_code", "A").strip().upper()
    try:
        role_code = RoleCode(role_raw)
    except ValueError:
        role_code = RoleCode.AUTHOR

    invoice_num_raw = row.get("invoice_number", "0")
    try:
        invoice_number = int(invoice_num_raw) if invoice_num_raw else 0
    except ValueError:
        invoice_number = 0

    telegram = row.get("telegram", "")

    common = dict(
        id=row.get("id", ""),
        aliases=aliases,
        role_code=role_code,
        email=row.get("email", ""),
        bank_name=row.get("bank_name", ""),
        bank_account=row.get("bank_account", ""),
        mags=row.get("mags", ""),
        invoice_number=invoice_number,
        telegram=telegram,
        secret_code=row.get("secret_code", ""),
    )

    cls = CONTRACTOR_CLASS_BY_TYPE[contractor_type]
    specific = {
        field: row.get(field, "")
        for field in cls.FIELD_META
        if field not in common
    }

    try:
        return cls(**common, **specific)
    except ValidationError as e:
        cid = row.get("id", "???")
        logger.warning("Skipping contractor %s — missing fields: %s", cid, e)
        return None


def load_all_contractors() -> list[Contractor]:
    """Load all contractors from all three sheets."""
    contractors: list[Contractor] = []
    for sheet_name, (ctype, _currency) in SHEET_CONFIG.items():
        rows = _sheets.read_as_dicts(CONTRACTORS_SHEET_ID, _sheet_range(sheet_name))
        for r in rows:
            if r.get("id"):
                c = _parse_contractor(r, ctype)
                if c is not None:
                    contractors.append(c)
    return contractors


def _similarity(a: str, b: str) -> float:
    """Case-insensitive similarity ratio between two strings."""
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def fuzzy_find(
    query: str, contractors: list[Contractor], threshold: float = 0.8
) -> list[tuple[Contractor, float]]:
    """Find contractors matching the query by name/alias. Returns sorted (best first)."""
    query_lower = query.lower().strip()
    results: list[tuple[Contractor, float]] = []

    for c in contractors:
        best_score = 0.0
        for name in c.all_names:
            name_lower = name.lower().strip()
            if query_lower in name_lower or name_lower in query_lower:
                score = 0.95
            else:
                score = _similarity(query_lower, name_lower)
            best_score = max(best_score, score)
        if best_score >= threshold:
            results.append((c, best_score))

    results.sort(key=lambda x: x[1], reverse=True)
    return results


def find_contractor_by_id(contractor_id: str, contractors: list[Contractor]) -> Optional[Contractor]:
    """Find a contractor by their unique ID."""
    for c in contractors:
        if c.id == contractor_id:
            return c
    return None


def find_contractor(query: str, contractors: list[Contractor]) -> Optional[Contractor]:
    """Find the single best matching contractor, or None."""
    matches = fuzzy_find(query, contractors)
    if matches and matches[0][1] >= 0.8:
        return matches[0][0]
    return None


def find_contractor_strict(query: str, contractors: list[Contractor]) -> Optional[Contractor]:
    """Find a contractor by exact name/alias match (case-insensitive)."""
    query_norm = query.lower().strip()
    for c in contractors:
        for name in c.all_names:
            if name.lower().strip() == query_norm:
                return c
    return None


def find_contractor_by_telegram_id(telegram_id: int, contractors: list[Contractor]) -> Optional[Contractor]:
    """Find a contractor already bound to this Telegram user ID."""
    tid = str(telegram_id)
    for c in contractors:
        if c.telegram == tid:
            return c
    return None


def _find_contractor_in_sheets(contractor_id: str) -> tuple[str, list[list[str]], int] | None:
    """Find which sheet a contractor lives in. Returns (sheet_name, rows, row_idx) or None."""
    for sheet_name in SHEET_CONFIG:
        range_name = _sheet_range(sheet_name)
        rows = _sheets.read(CONTRACTORS_SHEET_ID, range_name)
        if not rows:
            continue
        for idx, row in enumerate(rows[1:], start=1):
            if len(row) > 0 and row[0] == contractor_id:
                return sheet_name, rows, idx
    return None


def bind_telegram_id(contractor_id: str, telegram_id: int) -> None:
    """Write the Telegram user ID into the contractor's row in the sheet."""
    result = _find_contractor_in_sheets(contractor_id)
    if result is None:
        logger.error("Contractor %s not found in any sheet", contractor_id)
        return

    sheet_name, rows, row_idx = result
    headers = [h.strip().lower() for h in rows[0]]
    try:
        tg_col_idx = headers.index("telegram")
    except ValueError:
        logger.error("telegram column not found in sheet %s", sheet_name)
        return

    col_letter = _index_to_column_letter(tg_col_idx)
    cell_address = f"'{sheet_name}'!{col_letter}{row_idx + 1}"
    _sheets.write(CONTRACTORS_SHEET_ID, cell_address, [[str(telegram_id)]])
    logger.info("Bound telegram_id %s to contractor %s", telegram_id, contractor_id)


def contractor_to_row(c: Contractor) -> list[str]:
    """Convert a Contractor to a row for appending to its type-specific sheet."""
    columns = type(c).SHEET_COLUMNS
    row: list[str] = []
    for col in columns:
        if col == "aliases":
            row.append(", ".join(c.aliases))
        elif col == "role_code":
            row.append(c.role_code.value)
        elif col == "invoice_number":
            row.append(str(c.invoice_number))
        else:
            row.append(getattr(c, col, ""))
    return row


def save_contractor(c: Contractor) -> None:
    """Append a new contractor to the correct sheet based on type."""
    sheet_name = SHEET_NAME_BY_TYPE[c.type]
    _sheets.append(CONTRACTORS_SHEET_ID, _sheet_range(sheet_name), [contractor_to_row(c)])
    logger.info("Saved contractor %s (%s) to sheet '%s'", c.id, c.display_name, sheet_name)


def next_contractor_id(contractors: list[Contractor]) -> str:
    """Generate the next sequential contractor ID like c042."""
    max_num = 0
    for c in contractors:
        if c.id.startswith("c") and c.id[1:].isdigit():
            max_num = max(max_num, int(c.id[1:]))
    return f"c{max_num + 1:03d}"


def increment_invoice_number(contractor_id: str) -> int:
    """Increment invoice_number for a contractor and write to sheet. Returns the new number."""
    result = _find_contractor_in_sheets(contractor_id)
    if result is None:
        logger.error("Contractor %s not found in any sheet", contractor_id)
        return 1

    sheet_name, rows, contractor_row_idx = result
    headers = [h.strip().lower() for h in rows[0]]
    try:
        invoice_num_col_idx = headers.index("invoice_number")
    except ValueError:
        logger.error("invoice_number column not found in sheet %s", sheet_name)
        return 1

    current_val = rows[contractor_row_idx][invoice_num_col_idx] if invoice_num_col_idx < len(rows[contractor_row_idx]) else "0"
    try:
        current_num = int(current_val) if current_val else 0
    except ValueError:
        current_num = 0

    new_num = current_num + 1

    col_letter = _index_to_column_letter(invoice_num_col_idx)
    cell_address = f"'{sheet_name}'!{col_letter}{contractor_row_idx + 1}"
    _sheets.write(CONTRACTORS_SHEET_ID, cell_address, [[str(new_num)]])
    logger.info(f"Updated {contractor_id} invoice_number to {new_num}")

    return new_num


def pop_random_secret_code() -> str:
    """Pick a random secret code from the 'secret_codes' sheet and delete that row."""
    rows = _sheets.read(CONTRACTORS_SHEET_ID, "'secret_codes'!A:A")
    codes = [(i, row[0].strip()) for i, row in enumerate(rows) if row and row[0].strip()]
    if not codes:
        logger.warning("No secret codes left in the sheet")
        return ""
    idx, code = random.choice(codes)
    # Clear the used cell
    _sheets.write(CONTRACTORS_SHEET_ID, f"'secret_codes'!A{idx + 1}", [[""]])
    logger.info("Used secret code from row %d", idx + 1)
    return code


def _index_to_column_letter(idx: int) -> str:
    """Convert 0-based column index to letter (0->A, 1->B, ..., 26->AA)."""
    result = ""
    idx += 1
    while idx > 0:
        idx -= 1
        result = chr(65 + (idx % 26)) + result
        idx //= 26
    return result
