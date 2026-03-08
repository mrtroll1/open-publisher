"""Use case: parse a bank CSV statement and optionally upload to Airtable."""

from __future__ import annotations

import csv
import logging
import re
from datetime import datetime
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

# Contractor name patterns from bank descriptions
_TO_PATTERN = re.compile(r"^To (.+)$", re.IGNORECASE)
_FROM_PATTERN = re.compile(r"^From (.+)$", re.IGNORECASE)


class ParseBankStatement:
    """Orchestrates CSV parsing, categorization, and optional Airtable upload."""

    def __init__(self, airtable_gw: AirtableGateway | None = None):
        self._airtable = airtable_gw or AirtableGateway()

    def execute(
        self, filepath: str | Path, aed_to_rub: float, *, upload: bool = False,
    ) -> list[AirtableExpense]:
        """Parse a Wio Bank CSV and produce Airtable expense records.

        Args:
            filepath: Path to the bank statement CSV.
            aed_to_rub: Exchange rate AED -> RUB.
            upload: If True, upload to Airtable after parsing.

        Returns:
            List of AirtableExpense records.
        """
        filepath = Path(filepath)
        rows = _read_csv(filepath)
        expenses = _categorize_transactions(rows, aed_to_rub)

        if upload:
            self._airtable.upload_expenses(expenses)

        return expenses


def _read_csv(filepath: Path) -> list[dict[str, str]]:
    with open(filepath, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


def _to_rub(aed_amount: Decimal, rate: float) -> float:
    return float(round(float(aed_amount) * rate, 2))


def _month_label(date_str: str) -> str:
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        months = [
            "", "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ]
        return f"{months[d.month]} {d.year}"
    except ValueError:
        return date_str


def _bo(unit: str) -> str:
    return f"backoffice {unit}"


def _classify_person(name: str) -> tuple[str, str, str, str]:
    info = KNOWN_PEOPLE.get(name)
    if info:
        return info["group"], info["parent"], info["unit"], info["desc"]
    return "authors", "staff", UNIT_PRIMARY, "Гонорар автора"


def _is_owner(name: str) -> bool:
    return any(kw in name for kw in OWNER_KEYWORDS)


def _match_service(description: str) -> dict | None:
    desc_lower = description.lower().strip()
    for key, service in SERVICE_MAP.items():
        if key.lower() in desc_lower:
            return service
    return None


# ---------------------------------------------------------------------------
#  Per-category matchers for _categorize_transactions
# ---------------------------------------------------------------------------

def _handle_incoming_transfer(
    description: str, amount: Decimal, date_str: str, aed_to_rub: float,
    expenses: list[AirtableExpense],
) -> bool:
    from_match = _FROM_PATTERN.match(description)
    if not from_match:
        return True
    sender = from_match.group(1).strip()
    if "NETWORK INTERNATIONAL" in sender.upper():
        return True
    if _is_owner(sender):
        expenses.append(AirtableExpense(
            payed=date_str, amount_rub=_to_rub(abs(amount), aed_to_rub),
            contractor=OWNER_NAME, unit=_bo(UNIT_PRIMARY), entity=DEFAULT_ENTITY,
            description="Зп + амазон + авторы", group="managers", parent="staff",
        ))
    return True


def _handle_fee(  # noqa: PLR0913
    description: str, amount: Decimal, date_str: str, aed_to_rub: float,
    expenses: list[AirtableExpense], *,
    swift_fees: list[dict], fx_fees: list[dict],
) -> bool:
    if "Swift" in description or "SWIFT" in description:
        swift_fees.append({"date": date_str, "amount": amount})
        return True
    if "Foreign exchange" in description:
        fx_fees.append({"date": date_str, "amount": amount})
        return True
    if "Subscription fee" in description:
        rub = _to_rub(abs(amount), aed_to_rub)
        expenses.append(AirtableExpense(
            payed=date_str,
            amount_rub=rub,
            contractor="Wio Bank",
            unit=DEFAULT_ENTITY.split("-")[0] if DEFAULT_ENTITY else "",
            entity=DEFAULT_ENTITY,
            description=description,
            group="banking",
            parent="goods and services",
        ))
    return True


def _handle_outgoing_transfer(
    description: str, amount: Decimal, date_str: str, aed_to_rub: float,
    expenses: list[AirtableExpense],
) -> bool:
    to_match = _TO_PATTERN.match(description)
    if not to_match:
        return True  # no "To" pattern — skip

    name = to_match.group(1).strip()
    rub = _to_rub(abs(amount), aed_to_rub)
    group, parent, unit, desc = _classify_person(name)
    expenses.append(AirtableExpense(
        payed=date_str,
        amount_rub=rub,
        contractor=name,
        unit=unit,
        entity=DEFAULT_ENTITY,
        description=desc,
        group=group,
        parent=parent,
    ))
    return True


def _split_expense(date_str, rub_half, service) -> list[AirtableExpense]:
    return [
        AirtableExpense(
            payed=date_str, amount_rub=rub_half,
            contractor=service["contractor"], unit=_bo(unit_name),
            entity=DEFAULT_ENTITY, description=service["description"],
            group=service["group"], parent=service["parent"], splited="checked",
        )
        for unit_name in (UNIT_SECONDARY, UNIT_PRIMARY)
    ]


def _handle_card_known_service(
    service: dict, amount: Decimal, date_str: str, aed_to_rub: float,
    expenses: list[AirtableExpense],
) -> None:
    if service.get("split"):
        expenses.extend(_split_expense(date_str, _to_rub(abs(amount) / 2, aed_to_rub), service))
    else:
        rub = _to_rub(abs(amount), aed_to_rub)
        expenses.append(AirtableExpense(
            payed=date_str, amount_rub=rub, contractor=service["contractor"],
            unit=service["unit"], entity=DEFAULT_ENTITY,
            description=service["description"],
            group=service["group"], parent=service["parent"],
        ))


def _handle_card_unknown_service(
    description: str, amount: Decimal, date_str: str, aed_to_rub: float,
    expenses: list[AirtableExpense],
) -> None:
    half = abs(amount) / 2
    rub_half = _to_rub(half, aed_to_rub)
    expenses.extend(
        AirtableExpense(
            payed=date_str,
            amount_rub=rub_half,
            contractor=description,
            unit=_bo(unit_name),
            entity=DEFAULT_ENTITY,
            description=f"Оплата картой: {description}",
            group="infrastructure",
            parent="goods and services",
            splited="checked",
            comment="NEEDS REVIEW",
        )
        for unit_name in (UNIT_SECONDARY, UNIT_PRIMARY)
    )


def _handle_card_payment(
    description: str, amount: Decimal, date_str: str, aed_to_rub: float,
    expenses: list[AirtableExpense],
) -> bool:
    service = _match_service(description)
    if service:
        _handle_card_known_service(service, amount, date_str, aed_to_rub, expenses)
    else:
        _handle_card_unknown_service(description, amount, date_str, aed_to_rub, expenses)
    return True


def _aggregate_swift_fees(
    swift_fees: list[dict], aed_to_rub: float, expenses: list[AirtableExpense],
) -> None:
    if not swift_fees:
        return
    total_swift = sum(abs(f["amount"]) for f in swift_fees)
    rub = _to_rub(total_swift, aed_to_rub)
    last_date = max(f["date"] for f in swift_fees)
    expenses.append(AirtableExpense(
        payed=last_date,
        amount_rub=rub,
        contractor="Wio Bank",
        unit=_bo(UNIT_PRIMARY),
        entity=DEFAULT_ENTITY,
        description=f"SWIFT transaction fees {_month_label(last_date)}",
        group="comissions",
        parent="expenses",
    ))


def _aggregate_fx_fees(
    fx_fees: list[dict], aed_to_rub: float, expenses: list[AirtableExpense],
) -> None:
    if not fx_fees:
        return
    last_date = max(f["date"] for f in fx_fees)
    rub_half = _to_rub(sum(abs(f["amount"]) for f in fx_fees) / 2, aed_to_rub)
    expenses.extend(
        AirtableExpense(
            payed=last_date, amount_rub=rub_half, contractor="Wio Bank",
            unit=_bo(unit_name), entity=DEFAULT_ENTITY,
            description=f"Foreign exchange transaction fees {_month_label(last_date)}",
            group="comissions", parent="expenses", splited="checked",
        )
        for unit_name in (UNIT_SECONDARY, UNIT_PRIMARY)
    )


def _parse_row(row: dict[str, str]) -> tuple[str, str, Decimal, str] | None:
    try:
        return (row.get("Transaction type", "").strip(),
                row.get("Description", "").strip(),
                Decimal(row.get("Amount", "0").strip()),
                row.get("Date", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _categorize_transactions(rows: list[dict[str, str]], aed_to_rub: float) -> list[AirtableExpense]:
    expenses, swift_fees, fx_fees = [], [], []
    for row in rows:
        parsed = _parse_row(row)
        if parsed:
            _route_transaction(*parsed, aed_to_rub,
                               expenses=expenses, swift_fees=swift_fees, fx_fees=fx_fees)
    _aggregate_swift_fees(swift_fees, aed_to_rub, expenses)
    _aggregate_fx_fees(fx_fees, aed_to_rub, expenses)
    return expenses


def _route_transaction(  # noqa: PLR0913
    txn_type, description, amount, date_str, aed_to_rub, *,
    expenses, swift_fees, fx_fees,
):
    if txn_type == "Transfers" and amount > 0:
        _handle_incoming_transfer(description, amount, date_str, aed_to_rub, expenses)
    elif txn_type == "Fees":
        _handle_fee(description, amount, date_str, aed_to_rub, expenses, swift_fees=swift_fees, fx_fees=fx_fees)
    elif txn_type == "Transfers" and amount < 0:
        _handle_outgoing_transfer(description, amount, date_str, aed_to_rub, expenses)
    elif txn_type == "Card" and amount < 0:
        _handle_card_payment(description, amount, date_str, aed_to_rub, expenses)
