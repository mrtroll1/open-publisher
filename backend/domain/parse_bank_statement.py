"""Use case: parse a bank CSV statement and optionally upload to Airtable."""

from __future__ import annotations

import csv
import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from common.config import (
    DEFAULT_ENTITY,
    KNOWN_PEOPLE,
    OWNER_KEYWORDS,
    OWNER_NAME,
    SERVICE_MAP,
    UNIT_PRIMARY,
    UNIT_SECONDARY,
)
from common.models import AirtableExpense
from backend.infrastructure.gateways.airtable_gateway import AirtableGateway

logger = logging.getLogger(__name__)

# Contractor name patterns from bank descriptions
_TO_PATTERN = re.compile(r"^To (.+)$", re.IGNORECASE)
_FROM_PATTERN = re.compile(r"^From (.+)$", re.IGNORECASE)


class ParseBankStatement:
    """Orchestrates CSV parsing, categorization, and optional Airtable upload."""

    def __init__(self):
        self._airtable = AirtableGateway()

    def execute(
        self, filepath: str | Path, aed_to_rub: float, upload: bool = False,
    ) -> list[AirtableExpense]:
        """Parse a Wio Bank CSV and produce Airtable expense records.

        Args:
            filepath: Path to the bank statement CSV.
            aed_to_rub: Exchange rate AED → RUB.
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
    """Read CSV file and return list of row dicts."""
    with open(filepath, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


def _to_rub(aed_amount: Decimal, rate: float) -> float:
    """Convert AED to RUB as a number."""
    return float(round(float(aed_amount) * rate, 2))


def _format_date(date_str: str) -> str:
    """Keep date as ISO format 'YYYY-MM-DD' for Airtable."""
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return date_str
    except ValueError:
        return date_str


def _month_label(date_str: str) -> str:
    """Extract month name from date string."""
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
    """Backoffice unit shorthand."""
    return f"backoffice {unit}"


def _classify_person(name: str) -> tuple[str, str, str, str]:
    """Classify a person transfer. Returns (group, parent, unit, description)."""
    info = KNOWN_PEOPLE.get(name)
    if info:
        return info["group"], info["parent"], info["unit"], info["desc"]
    return "authors", "staff", UNIT_PRIMARY, "Гонорар автора"


def _is_owner(name: str) -> bool:
    """Check if a transfer name matches the owner."""
    return any(kw in name for kw in OWNER_KEYWORDS)


def _match_service(description: str) -> dict | None:
    """Match a card payment description to a known service."""
    desc_lower = description.lower().strip()
    for key, service in SERVICE_MAP.items():
        if key.lower() in desc_lower:
            return service
    return None


def _categorize_transactions(rows: list[dict[str, str]], aed_to_rub: float) -> list[AirtableExpense]:
    """Categorize all CSV rows into AirtableExpense records."""
    expenses: list[AirtableExpense] = []
    swift_fees: list[dict] = []
    fx_fees: list[dict] = []

    for row in rows:
        txn_type = row.get("Transaction type", "").strip()
        description = row.get("Description", "").strip()
        amount_str = row.get("Amount", "0").strip()
        date_str = row.get("Date", "").strip()

        try:
            amount = Decimal(amount_str)
        except (InvalidOperation, ValueError):
            continue

        # Skip income (positive transfers from NETWORK INTERNATIONAL = Stripe)
        if txn_type == "Transfers" and amount > 0:
            from_match = _FROM_PATTERN.match(description)
            if from_match:
                sender = from_match.group(1).strip()
                if "NETWORK INTERNATIONAL" in sender.upper():
                    continue
                if _is_owner(sender):
                    rub = _to_rub(abs(amount), aed_to_rub)
                    expenses.append(AirtableExpense(
                        payed=_format_date(date_str),
                        amount_rub=rub,
                        contractor=OWNER_NAME,
                        unit=_bo(UNIT_PRIMARY),
                        entity=DEFAULT_ENTITY,
                        description="Зп + амазон + авторы",
                        group="managers",
                        parent="staff",
                    ))
                    continue
                continue

        # Fees
        if txn_type == "Fees":
            if "Swift" in description or "SWIFT" in description:
                swift_fees.append({"date": date_str, "amount": amount})
                continue
            if "Foreign exchange" in description:
                fx_fees.append({"date": date_str, "amount": amount})
                continue
            if "Subscription fee" in description:
                rub = _to_rub(abs(amount), aed_to_rub)
                expenses.append(AirtableExpense(
                    payed=_format_date(date_str),
                    amount_rub=rub,
                    contractor="Wio Bank",
                    unit=DEFAULT_ENTITY.split("-")[0] if DEFAULT_ENTITY else "",
                    entity=DEFAULT_ENTITY,
                    description=description,
                    group="banking",
                    parent="goods and services",
                ))
                continue
            continue

        # Outgoing transfers (To <Name>)
        if txn_type == "Transfers" and amount < 0:
            to_match = _TO_PATTERN.match(description)
            if to_match:
                name = to_match.group(1).strip()
                rub = _to_rub(abs(amount), aed_to_rub)
                group, parent, unit, desc = _classify_person(name)
                expenses.append(AirtableExpense(
                    payed=_format_date(date_str),
                    amount_rub=rub,
                    contractor=name,
                    unit=unit,
                    entity=DEFAULT_ENTITY,
                    description=desc,
                    group=group,
                    parent=parent,
                ))
                continue

        # Card payments (services)
        if txn_type == "Card" and amount < 0:
            service = _match_service(description)
            if service:
                if service.get("split"):
                    half = abs(amount) / 2
                    rub_half = _to_rub(half, aed_to_rub)
                    for unit_name in (UNIT_SECONDARY, UNIT_PRIMARY):
                        expenses.append(AirtableExpense(
                            payed=_format_date(date_str),
                            amount_rub=rub_half,
                            contractor=service["contractor"],
                            unit=_bo(unit_name),
                            entity=DEFAULT_ENTITY,
                            description=service["description"],
                            group=service["group"],
                            parent=service["parent"],
                            splited="checked",
                        ))
                else:
                    rub = _to_rub(abs(amount), aed_to_rub)
                    expenses.append(AirtableExpense(
                        payed=_format_date(date_str),
                        amount_rub=rub,
                        contractor=service["contractor"],
                        unit=service["unit"],
                        entity=DEFAULT_ENTITY,
                        description=service["description"],
                        group=service["group"],
                        parent=service["parent"],
                    ))
            else:
                half = abs(amount) / 2
                rub_half = _to_rub(half, aed_to_rub)
                for unit_name in (UNIT_SECONDARY, UNIT_PRIMARY):
                    expenses.append(AirtableExpense(
                        payed=_format_date(date_str),
                        amount_rub=rub_half,
                        contractor=description,
                        unit=_bo(unit_name),
                        entity=DEFAULT_ENTITY,
                        description=f"Оплата картой: {description}",
                        group="infrastructure",
                        parent="goods and services",
                        splited="checked",
                        comment="NEEDS REVIEW",
                    ))
            continue

    # Aggregate SWIFT fees for the month
    if swift_fees:
        total_swift = sum(abs(f["amount"]) for f in swift_fees)
        rub = _to_rub(total_swift, aed_to_rub)
        last_date = max(f["date"] for f in swift_fees)
        expenses.append(AirtableExpense(
            payed=_format_date(last_date),
            amount_rub=rub,
            contractor="Wio Bank",
            unit=_bo(UNIT_PRIMARY),
            entity=DEFAULT_ENTITY,
            description=f"SWIFT transaction fees {_month_label(last_date)}",
            group="comissions",
            parent="expenses",
        ))

    # Aggregate FX fees for the month — split 50/50
    if fx_fees:
        total_fx = sum(abs(f["amount"]) for f in fx_fees)
        half_fx = total_fx / 2
        rub_half = _to_rub(half_fx, aed_to_rub)
        last_date = max(f["date"] for f in fx_fees)
        for unit_name in (UNIT_SECONDARY, UNIT_PRIMARY):
            expenses.append(AirtableExpense(
                payed=_format_date(last_date),
                amount_rub=rub_half,
                contractor="Wio Bank",
                unit=_bo(unit_name),
                entity=DEFAULT_ENTITY,
                description=f"Foreign exchange transaction fees {_month_label(last_date)}",
                group="comissions",
                parent="expenses",
                splited="checked",
            ))

    return expenses
