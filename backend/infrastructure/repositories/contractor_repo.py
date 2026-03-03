"""Backward-compatible shim — moved to backend.infrastructure.repositories.sheets.contractor_repo"""

from backend.infrastructure.repositories.sheets.contractor_repo import *  # noqa: F401,F403
from backend.infrastructure.repositories.sheets.contractor_repo import (  # noqa: F401
    SHEET_CONFIG,
    SHEET_NAME_BY_TYPE,
    _find_contractor_in_sheets,
    _parse_contractor,
    _sheet_range,
    _similarity,
    _write_cell,
)
