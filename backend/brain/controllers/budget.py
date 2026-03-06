"""Budget controller — monthly budget computation."""

from __future__ import annotations

from datetime import date

from backend.brain.base_controller import BaseController, BasePreparer
from backend.commands.budget import ComputeBudgetUseCase


def prev_month() -> str:
    """Return YYYY-MM for the previous month."""
    today = date.today()
    if today.month == 1:
        return f"{today.year - 1}-12"
    return f"{today.year}-{today.month - 1:02d}"


class BudgetPreparer(BasePreparer):
    def prepare(self, input: str, env: dict, user: dict) -> dict:
        return {"month": input.strip() or prev_month()}


class BudgetController(BaseController):
    def __init__(self, compute_budget):
        super().__init__(BudgetPreparer(), ComputeBudgetUseCase(compute_budget))
