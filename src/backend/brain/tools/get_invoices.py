from __future__ import annotations

import re
from datetime import date

from backend.brain.tool import Tool, ToolContext
from backend.infrastructure.repositories.sheets.contractor_repo import (
    fuzzy_find,
    load_all_contractors,
)
from backend.infrastructure.repositories.sheets.invoice_repo import load_invoices

_MONTH_RE = re.compile(r"\b(\d{4}-\d{2})\b")


def _current_month() -> str:
    today = date.today()
    return f"{today.year}-{today.month:02d}"


def _parse_input(raw: str) -> tuple[str, str]:
    """Extract month (YYYY-MM) and contractor query from a mixed input string."""
    m = _MONTH_RE.search(raw)
    month = m.group(1) if m else ""
    contractor = _MONTH_RE.sub("", raw).strip() if m else raw.strip()
    return contractor, month


def _serialize(inv) -> dict:
    return {
        "contractor_name": inv.contractor_name,
        "invoice_number": inv.invoice_number,
        "amount": str(inv.amount),
        "currency": inv.currency.value,
        "status": inv.status.value,
        "gdrive_path": inv.gdrive_path,
        "legium_link": inv.legium_link,
    }


def make_get_invoices_tool() -> Tool:
    def fn(args: dict, _ctx: ToolContext) -> dict:
        month = args.get("month", "").strip()
        contractor_query = args.get("contractor", "").strip()
        # Slash command sends everything as "contractor" — extract month if embedded
        if contractor_query and not month:
            contractor_query, month = _parse_input(contractor_query)
        month = month or _current_month()

        invoices = load_invoices(month)
        if contractor_query:
            contractors = load_all_contractors()
            matches = fuzzy_find(contractor_query, contractors, threshold=0.4)
            matched_ids = {c.id for c, _ in matches}
            invoices = [inv for inv in invoices if inv.contractor_id in matched_ids]

        return {
            "invoices": [_serialize(inv) for inv in invoices],
            "month": month,
            "filter": contractor_query or None,
        }

    return Tool(
        name="get_invoices",
        description="Получить список уже сгенерированных счетов за месяц. Можно фильтровать по имени контрагента.",
        parameters={
            "type": "object",
            "properties": {
                "month": {"type": "string", "description": "Месяц в формате YYYY-MM (по умолчанию текущий)"},
                "contractor": {"type": "string", "description": "Имя или псевдоним контрагента для поиска"},
            },
        },
        fn=fn,
        permissions={},
        slash_command="invoices",
        nl_routable=False,
        conversational=True,
        nl_param="contractor",
    )
