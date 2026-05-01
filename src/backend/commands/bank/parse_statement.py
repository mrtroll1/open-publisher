"""Use case: parse a Bunq CSV statement and optionally upload to Airtable."""

from __future__ import annotations

import csv
import logging
from decimal import Decimal, InvalidOperation
from pathlib import Path

from backend.config import (
    DEFAULT_ENTITY,
    KNOWN_PEOPLE,
    OWNER_KEYWORDS,
    OWNER_NAME,
    SERVICE_MAP,
    UNIT_PRIMARY,
    UNIT_SECONDARY,
)
from backend.infrastructure.gateways.airtable_gateway import AirtableGateway
from backend.models import AirtableExpense

logger = logging.getLogger(__name__)

_BUNQ_BANK_NAME = "bunq BV"


class ParseBankStatement:
    """Orchestrates Bunq CSV parsing, categorization, and optional Airtable upload."""

    def __init__(self, airtable_gw: AirtableGateway | None = None):
        self._airtable = airtable_gw or AirtableGateway()

    def execute(
        self, filepath: str | Path, eur_to_rub: float, *, upload: bool = False,
    ) -> list[AirtableExpense]:
        """Parse a Bunq CSV and produce Airtable expense records.

        Income (positive amounts) is ignored.

        Args:
            filepath: Path to the Bunq statement CSV.
            eur_to_rub: Exchange rate EUR -> RUB.
            upload: If True, upload to Airtable after parsing.

        Returns:
            List of AirtableExpense records.
        """
        filepath = Path(filepath)
        rows = _read_csv(filepath)
        expenses = _categorize_transactions(rows, eur_to_rub)

        if upload:
            self._airtable.upload_expenses(expenses)

        return expenses


def _read_csv(filepath: Path) -> list[dict[str, str]]:
    with open(filepath, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        return list(reader)


def _parse_eur(s: str) -> Decimal:
    # European format: "2.558,38" -> Decimal("2558.38")
    return Decimal(s.replace(".", "").replace(",", "."))


def _to_rub(eur_amount: Decimal, rate: float) -> float:
    return float(round(float(eur_amount) * rate, 2))


def _bo(unit: str) -> str:
    return f"backoffice {unit}"


def _classify_person(name: str) -> tuple[str, str, str]:
    info = KNOWN_PEOPLE.get(name)
    if info:
        return info["group"], info["unit"], info["desc"]
    return "authors", UNIT_PRIMARY, "Гонорар автора"


def _is_owner(name: str) -> bool:
    return any(kw in name for kw in OWNER_KEYWORDS)


def _match_service(haystack: str) -> dict | None:
    h = haystack.lower().strip()
    for key, service in SERVICE_MAP.items():
        if key.lower() in h:
            return service
    return None


def _looks_like_card(name: str, description: str) -> bool:
    # Bunq card payments have a description that starts with the merchant name
    if not name or not description:
        return False
    return description.upper().startswith(name.upper())


# ---------------------------------------------------------------------------
#  Per-category handlers
# ---------------------------------------------------------------------------

def _handle_bank_fee(
    description: str, amount: Decimal, date_str: str, eur_to_rub: float,
    expenses: list[AirtableExpense],
) -> None:
    expenses.append(AirtableExpense(
        payed=date_str,
        amount_rub=_to_rub(abs(amount), eur_to_rub),
        contractor="bunq",
        unit=_bo(UNIT_PRIMARY),
        entity=DEFAULT_ENTITY,
        description=description or "bunq fee",
        group="banking",
    ))


def _handle_owner_withdrawal(
    amount: Decimal, date_str: str, eur_to_rub: float,
    expenses: list[AirtableExpense],
) -> None:
    expenses.append(AirtableExpense(
        payed=date_str,
        amount_rub=_to_rub(abs(amount), eur_to_rub),
        contractor=OWNER_NAME,
        unit=_bo(UNIT_PRIMARY),
        entity=DEFAULT_ENTITY,
        description="Зп + амазон + авторы",
        group="managers",
    ))


def _handle_person_payment(
    name: str, amount: Decimal, date_str: str, eur_to_rub: float,
    expenses: list[AirtableExpense],
) -> None:
    group, unit, desc = _classify_person(name)
    expenses.append(AirtableExpense(
        payed=date_str,
        amount_rub=_to_rub(abs(amount), eur_to_rub),
        contractor=name,
        unit=unit,
        entity=DEFAULT_ENTITY,
        description=desc,
        group=group,
    ))


def _split_expense(date_str, rub_half, service) -> list[AirtableExpense]:
    return [
        AirtableExpense(
            payed=date_str, amount_rub=rub_half,
            contractor=service["contractor"], unit=_bo(unit_name),
            entity=DEFAULT_ENTITY, description=service["description"],
            group=service["group"], splited="checked",
        )
        for unit_name in (UNIT_SECONDARY, UNIT_PRIMARY)
    ]


def _handle_card_known_service(
    service: dict, amount: Decimal, date_str: str, eur_to_rub: float,
    expenses: list[AirtableExpense],
) -> None:
    if service.get("split"):
        expenses.extend(_split_expense(date_str, _to_rub(abs(amount) / 2, eur_to_rub), service))
    else:
        expenses.append(AirtableExpense(
            payed=date_str,
            amount_rub=_to_rub(abs(amount), eur_to_rub),
            contractor=service["contractor"],
            unit=service["unit"],
            entity=DEFAULT_ENTITY,
            description=service["description"],
            group=service["group"],
        ))


def _handle_card_unknown_service(
    name: str, amount: Decimal, date_str: str, eur_to_rub: float,
    expenses: list[AirtableExpense],
) -> None:
    rub_half = _to_rub(abs(amount) / 2, eur_to_rub)
    expenses.extend(
        AirtableExpense(
            payed=date_str,
            amount_rub=rub_half,
            contractor=name,
            unit=_bo(unit_name),
            entity=DEFAULT_ENTITY,
            description=f"Оплата картой: {name}",
            group="infrastructure",
            splited="checked",
            comment="NEEDS REVIEW",
        )
        for unit_name in (UNIT_SECONDARY, UNIT_PRIMARY)
    )


def _handle_card_payment(  # noqa: PLR0913
    name: str, description: str, amount: Decimal, date_str: str, eur_to_rub: float,
    expenses: list[AirtableExpense],
) -> None:
    service = _match_service(f"{name} {description}")
    if service:
        _handle_card_known_service(service, amount, date_str, eur_to_rub, expenses)
    else:
        _handle_card_unknown_service(name, amount, date_str, eur_to_rub, expenses)


# ---------------------------------------------------------------------------
#  Routing
# ---------------------------------------------------------------------------

def _parse_row(row: dict[str, str]) -> tuple[str, str, Decimal, str] | None:
    try:
        return (row.get("Name", "").strip(),
                row.get("Description", "").strip(),
                _parse_eur(row.get("Amount", "0").strip()),
                row.get("Date", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _route(  # noqa: PLR0913
    name: str, description: str, amount: Decimal, date_str: str, eur_to_rub: float,
    expenses: list[AirtableExpense],
) -> None:
    if name == _BUNQ_BANK_NAME:
        _handle_bank_fee(description, amount, date_str, eur_to_rub, expenses)
        return
    if _is_owner(name):
        _handle_owner_withdrawal(amount, date_str, eur_to_rub, expenses)
        return
    if _looks_like_card(name, description):
        _handle_card_payment(name, description, amount, date_str, eur_to_rub, expenses)
        return
    _handle_person_payment(name, amount, date_str, eur_to_rub, expenses)


def _categorize_transactions(
    rows: list[dict[str, str]], eur_to_rub: float,
) -> list[AirtableExpense]:
    expenses: list[AirtableExpense] = []
    for row in rows:
        parsed = _parse_row(row)
        if not parsed:
            continue
        name, description, amount, date_str = parsed
        if amount >= 0:
            continue  # ignore income (Stripe payouts, top-ups)
        _route(name, description, amount, date_str, eur_to_rub, expenses)
    return expenses
