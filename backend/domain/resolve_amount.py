"""Amount resolution and formatting helpers for invoices."""

from __future__ import annotations

from common.models import Contractor, Currency


def plural_ru(n: int, one: str, few: str, many: str) -> str:
    """Russian plural form: 1 публикация, 2 публикации, 5 публикаций."""
    mod100 = n % 100
    if 11 <= mod100 <= 19:
        return f"{n} {many}"
    mod10 = n % 10
    if mod10 == 1:
        return f"{n} {one}"
    if 2 <= mod10 <= 4:
        return f"{n} {few}"
    return f"{n} {many}"


def resolve_amount(
    budget_amounts: dict, contractor: Contractor, num_articles: int,
) -> tuple[int, str]:
    """Resolve invoice amount from budget sheet, with default-rate fallback.

    Returns (amount, explanation_str).
    """
    sym = "€" if contractor.currency == Currency.EUR else "₽"
    name_lower = contractor.display_name.lower().strip()
    budget_entry = budget_amounts.get(name_lower)
    if budget_entry:
        eur, rub, note = budget_entry
        amount = eur if contractor.currency == Currency.EUR else rub
        if amount:
            return amount, _format_budget_explanation(amount, note, sym)

    # Fallback: default rate × articles
    per_article = 10_000 if contractor.currency == Currency.RUB else 100
    amount = num_articles * per_article
    return amount, f"Сумма: {_fmt(amount)}{sym}"


def _fmt(v: int) -> str:
    return f"{v:_}".replace("_", " ")


def _format_budget_explanation(total: int, note: str, sym: str) -> str:
    """Format amount with redirect breakdown from column E.

    No redirects:  "Сумма: 2 700€"
    With redirects: "Сумма: 2 800€\\n2 500 по умолчанию\\n200 за Яна Заречная"
    """
    if not note:
        return f"Сумма: {_fmt(total)}{sym}"

    bonuses: list[tuple[str, int]] = []
    for part in note.split(","):
        part = part.strip()
        if "(" not in part or ")" not in part:
            continue
        idx_open = part.rfind("(")
        idx_close = part.rfind(")")
        name = part[:idx_open].strip()
        try:
            amt = int(part[idx_open + 1:idx_close].strip())
        except ValueError:
            continue
        if name and amt:
            bonuses.append((name, amt))

    if not bonuses:
        return f"Сумма: {_fmt(total)}{sym}"

    bonus_total = sum(amt for _, amt in bonuses)
    base = total - bonus_total
    lines = [f"Сумма: {_fmt(total)}{sym}"]
    lines.append(f"{_fmt(base)}{sym} по умолчанию")
    for name, amt in bonuses:
        lines.append(f"{_fmt(amt)}{sym} за {name}")
    return "\n".join(lines)
