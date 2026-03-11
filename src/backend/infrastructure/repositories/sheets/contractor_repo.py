"""Contractor lookup, fuzzy matching, and CRUD against Google Sheets."""

from __future__ import annotations

import logging
import random
from difflib import SequenceMatcher

from pydantic import ValidationError

from backend.config import CONTRACTORS_SHEET_ID
from backend.infrastructure.gateways.sheets_gateway import SheetsGateway
from backend.infrastructure.repositories.sheets.sheets_utils import index_to_column_letter
from backend.models import (
    CONTRACTOR_CLASS_BY_TYPE,
    Contractor,
    ContractorType,
    Currency,
    RoleCode,
    StubContractor,
)

logger = logging.getLogger(__name__)

_sheets = SheetsGateway()

# Sheet name -> (ContractorType, implicit Currency)
SHEET_CONFIG: dict[str, tuple[ContractorType, Currency]] = {
    "global": (ContractorType.GLOBAL, Currency.EUR),
    "ИП": (ContractorType.IP, Currency.RUB),
    "самозанятый": (ContractorType.SAMOZANYATY, Currency.RUB),
}

STUB_SHEET = "stub"

# Reverse lookup: ContractorType -> sheet name
SHEET_NAME_BY_TYPE: dict[ContractorType, str] = {
    v[0]: k for k, v in SHEET_CONFIG.items()
}


def _sheet_range(sheet_name: str) -> str:
    """Build the A1 range for a sheet, quoting names with special chars."""
    return f"'{sheet_name}'!A:Z"


def _parse_aliases(raw: str) -> list[str]:
    return [a.strip() for a in raw.split(",") if a.strip()]


def _parse_role(raw: str) -> tuple[RoleCode, bool]:
    role_raw = raw.strip().upper()
    is_photographer = role_raw.endswith(":F")
    if is_photographer:
        role_raw = role_raw.removesuffix(":F")
    try:
        return RoleCode(role_raw), is_photographer
    except ValueError:
        return RoleCode.AUTHOR, is_photographer


def _parse_int(raw: str, default: int = 0) -> int:
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _common_fields(row: dict[str, str]) -> dict:
    role_code, is_photographer = _parse_role(row.get("role_code", "A"))
    return dict(
        id=row.get("id", ""),
        aliases=_parse_aliases(row.get("aliases", "")),
        role_code=role_code,
        is_photographer=is_photographer,
        email=row.get("email", ""),
        bank_name=row.get("bank_name", ""),
        bank_account=row.get("bank_account", ""),
        mags=row.get("mags", ""),
        invoice_number=_parse_int(row.get("invoice_number", "0")),
        telegram=row.get("telegram", ""),
        secret_code=row.get("secret_code", ""),
    )


def _parse_contractor(
    row: dict[str, str],
    contractor_type: ContractorType,
) -> Contractor | None:
    common = _common_fields(row)
    cls = CONTRACTOR_CLASS_BY_TYPE[contractor_type]
    specific = {f: row.get(f, "") for f in cls.FIELD_META if f not in common}
    try:
        return cls(**common, **specific)
    except ValidationError as e:
        logger.warning("Skipping contractor %s — missing fields: %s", row.get("id", "???"), e)
        return None


def _parse_stub(row: dict[str, str]) -> StubContractor | None:
    role_code, is_photographer = _parse_role(row.get("role_code", "A"))
    try:
        return StubContractor(
            id=row.get("id", ""),
            name=row.get("name", ""),
            aliases=_parse_aliases(row.get("aliases", "")),
            role_code=role_code,
            is_photographer=is_photographer,
            email="",
            bank_name="",
            bank_account="",
            telegram=row.get("telegram", ""),
            secret_code=row.get("secret_code", ""),
        )
    except ValidationError as e:
        logger.warning("Skipping stub %s: %s", row.get("id", "???"), e)
        return None


def load_all_contractors() -> list[Contractor]:
    """Load all contractors from all typed sheets + stub sheet."""
    contractors: list[Contractor] = []
    for sheet_name, (ctype, _currency) in SHEET_CONFIG.items():
        rows = _sheets.read_as_dicts(CONTRACTORS_SHEET_ID, _sheet_range(sheet_name))
        for r in rows:
            if r.get("id"):
                c = _parse_contractor(r, ctype)
                if c is not None:
                    contractors.append(c)
    # Load stubs
    for r in _sheets.read_as_dicts(CONTRACTORS_SHEET_ID, _sheet_range(STUB_SHEET)):
        if r.get("id"):
            s = _parse_stub(r)
            if s is not None:
                contractors.append(s)
    return contractors


def _similarity(a: str, b: str) -> float:
    """Case-insensitive similarity ratio between two strings."""
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _normalize_words(text: str) -> set[str]:
    """Split into lowercase words."""
    return {w.strip() for w in text.lower().split() if w.strip()}


def _word_independent_score(query: str, name: str) -> float:
    """Score based on word overlap regardless of order."""
    q_words = _normalize_words(query)
    n_words = _normalize_words(name)
    if not q_words or not n_words:
        return 0.0
    overlap = q_words & n_words
    if not overlap:
        return 0.0
    return len(overlap) / max(len(q_words), len(n_words))


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
                seq_score = _similarity(query_lower, name_lower)
                word_score = _word_independent_score(query_lower, name_lower)
                score = max(seq_score, word_score)
            best_score = max(best_score, score)
        if best_score >= threshold:
            results.append((c, best_score))

    results.sort(key=lambda x: x[1], reverse=True)
    return results


def find_contractor_by_id(contractor_id: str, contractors: list[Contractor]) -> Contractor | None:
    """Find a contractor by their unique ID."""
    for c in contractors:
        if c.id == contractor_id:
            return c
    return None


def find_contractor(query: str, contractors: list[Contractor]) -> Contractor | None:
    """Find the single best matching contractor, or None."""
    matches = fuzzy_find(query, contractors)
    if matches and matches[0][1] >= 0.8:
        return matches[0][0]
    return None


def find_contractor_strict(query: str, contractors: list[Contractor]) -> Contractor | None:
    """Find a contractor by exact name/alias match (case-insensitive)."""
    query_norm = query.lower().strip()
    for c in contractors:
        for name in c.all_names:
            if name.lower().strip() == query_norm:
                return c
    return None


def find_contractor_by_telegram_id(telegram_id: int, contractors: list[Contractor]) -> Contractor | None:
    """Find a contractor already bound to this Telegram user ID."""
    tid = str(telegram_id)
    for c in contractors:
        if c.telegram == tid:
            return c
    return None


def _find_contractor_in_sheets(contractor_id: str) -> tuple[str, list[list[str]], int] | None:
    """Find which sheet a contractor lives in. Returns (sheet_name, rows, row_idx) or None."""
    for sheet_name in [*SHEET_CONFIG, STUB_SHEET]:
        range_name = _sheet_range(sheet_name)
        rows = _sheets.read(CONTRACTORS_SHEET_ID, range_name)
        if not rows:
            continue
        for idx, row in enumerate(rows[1:], start=1):
            if len(row) > 0 and row[0] == contractor_id:
                return sheet_name, rows, idx
    return None


def _write_cell(sheet_name: str, headers: list[str], row_idx: int, field: str, value: str) -> bool:
    """Find column by name and write value. Returns True on success."""
    try:
        col_idx = headers.index(field)
    except ValueError:
        logger.warning("Column %s not found in sheet %s", field, sheet_name)
        return False
    col_letter = index_to_column_letter(col_idx)
    cell = f"'{sheet_name}'!{col_letter}{row_idx + 1}"
    _sheets.write(CONTRACTORS_SHEET_ID, cell, [[value]])
    return True


def bind_telegram_id(contractor_id: str, telegram_id: int) -> None:
    """Write the Telegram user ID into the contractor's row in the sheet."""
    result = _find_contractor_in_sheets(contractor_id)
    if result is None:
        logger.error("Contractor %s not found in any sheet", contractor_id)
        return
    sheet_name, rows, row_idx = result
    headers = [h.strip().lower() for h in rows[0]]
    if _write_cell(sheet_name, headers, row_idx, "telegram", str(telegram_id)):
        logger.info("Bound telegram_id %s to contractor %s", telegram_id, contractor_id)


def _field_to_cell(c: Contractor, col: str) -> str:
    if col == "aliases":
        return ", ".join(c.aliases)
    if col == "role_code":
        return c.role_code.value + (":F" if c.is_photographer else "")
    if col == "invoice_number":
        return str(c.invoice_number)
    return getattr(c, col, "")


def contractor_to_row(c: Contractor) -> list[str]:
    return [_field_to_cell(c, col) for col in type(c).SHEET_COLUMNS]


def save_contractor(c: Contractor) -> None:
    """Append a new contractor to the correct sheet based on type."""
    sheet_name = SHEET_NAME_BY_TYPE[c.type]
    _sheets.append(CONTRACTORS_SHEET_ID, _sheet_range(sheet_name), [contractor_to_row(c)])
    logger.info("Saved contractor %s (%s) to sheet '%s'", c.id, c.display_name, sheet_name)


def save_stub(c: StubContractor) -> None:
    """Append a stub contractor to the stub sheet."""
    _sheets.append(CONTRACTORS_SHEET_ID, _sheet_range(STUB_SHEET), [contractor_to_row(c)])
    logger.info("Saved stub %s (%s) to sheet '%s'", c.id, c.display_name, STUB_SHEET)


def delete_contractor_from_sheet(contractor_id: str) -> bool:
    """Delete a contractor row from any sheet (typed or stub). Returns True if found."""
    all_sheets = [*SHEET_CONFIG, STUB_SHEET]
    for sheet_name in all_sheets:
        rows = _sheets.read(CONTRACTORS_SHEET_ID, _sheet_range(sheet_name))
        if not rows:
            continue
        for idx, row in enumerate(rows[1:], start=1):
            if len(row) > 0 and row[0] == contractor_id:
                _sheets.delete_row(CONTRACTORS_SHEET_ID, sheet_name, idx)
                logger.info("Deleted contractor %s from sheet '%s'", contractor_id, sheet_name)
                return True
    return False


def next_contractor_id(contractors: list[Contractor]) -> str:
    """Generate the next sequential contractor ID like c042."""
    max_num = 0
    for c in contractors:
        if c.id.startswith("c") and c.id[1:].isdigit():
            max_num = max(max_num, int(c.id[1:]))
    return f"c{max_num + 1:03d}"


def _read_current_invoice_number(rows: list[list[str]], headers: list[str], row_idx: int) -> int:
    try:
        col_idx = headers.index("invoice_number")
    except ValueError:
        return 0
    raw = rows[row_idx][col_idx] if col_idx < len(rows[row_idx]) else "0"
    return _parse_int(raw)


def increment_invoice_number(contractor_id: str) -> int:
    result = _find_contractor_in_sheets(contractor_id)
    if result is None:
        logger.error("Contractor %s not found in any sheet", contractor_id)
        return 1
    sheet_name, rows, row_idx = result
    headers = [h.strip().lower() for h in rows[0]]
    new_num = _read_current_invoice_number(rows, headers, row_idx) + 1
    _write_cell(sheet_name, headers, row_idx, "invoice_number", str(new_num))
    logger.info("Updated %s invoice_number to %d", contractor_id, new_num)
    return new_num


def pop_random_secret_code() -> str:
    """Pick a random secret code from the 'secret_codes' sheet and delete that row."""
    rows = _sheets.read(CONTRACTORS_SHEET_ID, "'secret_codes'!A:A")
    # Skip header row (index 0)
    codes = [(i, row[0].strip()) for i, row in enumerate(rows) if i > 0 and row and row[0].strip()]
    if not codes:
        logger.warning("No secret codes left in the sheet")
        return ""
    idx, code = random.choice(codes)
    # Clear the used cell
    _sheets.write(CONTRACTORS_SHEET_ID, f"'secret_codes'!A{idx + 1}", [[""]])
    logger.info("Used secret code from row %d", idx + 1)
    return code


def change_contractor_type(
    old_contractor: Contractor, new_type: ContractorType, new_data: dict[str, str],
) -> Contractor:
    """Delete old contractor, create new one with new type.

    Preserves: id, aliases, role_code, is_photographer, telegram, secret_code, mags.
    Resets: invoice_number to 0.
    Takes from new_data: all type-specific fields + email, bank fields.
    """
    delete_contractor_from_sheet(old_contractor.id)
    cls = CONTRACTOR_CLASS_BY_TYPE[new_type]
    kwargs = {
        "id": old_contractor.id,
        "aliases": old_contractor.aliases,
        "role_code": old_contractor.role_code,
        "is_photographer": old_contractor.is_photographer,
        "telegram": old_contractor.telegram,
        "secret_code": old_contractor.secret_code,
        "email": new_data.get("email", old_contractor.email),
        "bank_name": new_data.get("bank_name", ""),
        "bank_account": new_data.get("bank_account", ""),
        "mags": old_contractor.mags,
        "invoice_number": 0,
    }
    for field in cls.FIELD_META:
        if field not in kwargs:
            kwargs[field] = new_data.get(field, "")
    contractor = cls(**kwargs)
    save_contractor(contractor)
    logger.info("Changed %s type to %s", old_contractor.id, new_type.value)
    return contractor


def update_contractor_fields(contractor_id: str, updates: dict[str, str]) -> int:
    """Update specific fields for a contractor in their sheet. Returns number of fields updated."""
    result = _find_contractor_in_sheets(contractor_id)
    if result is None:
        logger.error("Contractor %s not found in any sheet", contractor_id)
        return 0
    sheet_name, rows, row_idx = result
    headers = [h.strip().lower() for h in rows[0]]
    count = sum(1 for f, v in updates.items() if _write_cell(sheet_name, headers, row_idx, f, v))
    logger.info("Updated %d fields for contractor %s", count, contractor_id)
    return count
