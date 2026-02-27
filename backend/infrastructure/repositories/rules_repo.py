"""Load payment rules from the Special Rules Google Sheet."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from common.config import SPECIAL_RULES_SHEET_ID
from backend.infrastructure.gateways.sheets_gateway import SheetsGateway

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


def load_redirect_rules() -> list[RedirectRule]:
    """Read payment_redirect_rules sheet."""
    rows = _sheets.read_as_dicts(SPECIAL_RULES_SHEET_ID, "'payment_redirect_rules'!A:Z")
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


def load_flat_rate_rules() -> list[FlatRateRule]:
    """Read flat_rate_rules sheet."""
    rows = _sheets.read_as_dicts(SPECIAL_RULES_SHEET_ID, "'flat_rate_rules'!A:Z")
    rules: list[FlatRateRule] = []
    for r in rows:
        name = r.get("name", "").strip()
        if not name:
            continue
        eur = _parse_int(r.get("eur", ""))
        rub = _parse_int(r.get("rub", ""))
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
        eur = _parse_int(r.get("eur", ""))
        rub = _parse_int(r.get("rub", ""))
        if eur or rub:
            rules.append(ArticleRateRule(contractor_id=cid, eur=eur, rub=rub))
    return rules


def _parse_int(val: str) -> int:
    try:
        return int(val.strip()) if val.strip() else 0
    except ValueError:
        return 0
