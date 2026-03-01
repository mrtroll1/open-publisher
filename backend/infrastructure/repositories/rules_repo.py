"""Load payment rules from the Special Rules Google Sheet."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from common.config import SPECIAL_RULES_SHEET_ID
from backend.infrastructure.gateways.sheets_gateway import SheetsGateway
from backend.infrastructure.repositories.sheets_utils import parse_int

logger = logging.getLogger(__name__)

_sheets = SheetsGateway()


@dataclass
class RedirectRule:
    """A payment redirect or exclusion rule."""
    source_name: str
    target_id: str       # empty → exclude author entirely
    add_to_total: bool


@dataclass
class FlatRateRule:
    """A flat-amount entry always included in the budget."""
    contractor_id: str   # empty for non-contractors (AFP, ElevenLabs)
    name: str
    label: str
    eur: int
    rub: int


@dataclass
class ArticleRateRule:
    """A per-article rate override for a contractor."""
    contractor_id: str
    eur: int
    rub: int


_REDIRECT_RANGE = "'payment_redirect_rules'!A:Z"


def load_redirect_rules() -> list[RedirectRule]:
    """Read payment_redirect_rules sheet."""
    rows = _sheets.read_as_dicts(SPECIAL_RULES_SHEET_ID, _REDIRECT_RANGE)
    rules: list[RedirectRule] = []
    for r in rows:
        source = r.get("source_name", "").strip()
        if not source:
            continue
        target = r.get("target_id", "").strip()
        add_raw = r.get("add_to_total", "").strip().upper()
        rules.append(RedirectRule(
            source_name=source,
            target_id=target,
            add_to_total=add_raw == "TRUE",
        ))
    return rules


def find_redirect_rules_by_target(target_id: str) -> list[RedirectRule]:
    """Find all redirect rules where the given contractor is the target."""
    return [r for r in load_redirect_rules() if r.target_id == target_id]


def add_redirect_rule(source_name: str, target_id: str) -> None:
    """Append a new redirect rule row to the sheet."""
    _sheets.append(
        SPECIAL_RULES_SHEET_ID,
        _REDIRECT_RANGE,
        [[source_name, target_id, "TRUE"]],
    )


def remove_redirect_rule(source_name: str, target_id: str) -> bool:
    """Remove a redirect rule. Returns True if found and removed."""
    raw_rows = _sheets.read(SPECIAL_RULES_SHEET_ID, _REDIRECT_RANGE)
    if len(raw_rows) < 2:
        return False
    for i, row in enumerate(raw_rows[1:], start=2):  # row 1 is header, data starts at 2
        src = (row[0] if len(row) > 0 else "").strip()
        tgt = (row[1] if len(row) > 1 else "").strip()
        if src == source_name and tgt == target_id:
            ncols = len(raw_rows[0])
            _sheets.clear(SPECIAL_RULES_SHEET_ID, f"'payment_redirect_rules'!A{i}:{chr(64 + ncols)}{i}")
            return True
    return False


def load_flat_rate_rules() -> list[FlatRateRule]:
    """Read flat_rate_rules sheet."""
    rows = _sheets.read_as_dicts(SPECIAL_RULES_SHEET_ID, "'flat_rate_rules'!A:Z")
    rules: list[FlatRateRule] = []
    for r in rows:
        name = r.get("name", "").strip()
        if not name:
            continue
        eur = parse_int(r.get("eur", ""))
        rub = parse_int(r.get("rub", ""))
        rules.append(FlatRateRule(
            contractor_id=r.get("contractor_id", "").strip(),
            name=name,
            label=r.get("label", "").strip(),
            eur=eur,
            rub=rub,
        ))
    return rules


def load_article_rate_rules() -> list[ArticleRateRule]:
    """Read per_article_rate_rules sheet."""
    rows = _sheets.read_as_dicts(SPECIAL_RULES_SHEET_ID, "'per_article_rate_rules'!A:Z")
    rules: list[ArticleRateRule] = []
    for r in rows:
        cid = r.get("contractor_id", "").strip()
        if not cid:
            continue
        eur = parse_int(r.get("eur", ""))
        rub = parse_int(r.get("rub", ""))
        if eur or rub:
            rules.append(ArticleRateRule(contractor_id=cid, eur=eur, rub=rub))
    return rules
