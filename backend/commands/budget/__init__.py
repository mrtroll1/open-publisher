"""Budget controllers."""

from __future__ import annotations

from datetime import date
from typing import Any

from backend.brain.base_controller import BaseController, BasePreparer, BaseUseCase


def prev_month() -> str:
    """Return YYYY-MM for the previous month."""
    today = date.today()
    if today.month == 1:
        return f"{today.year - 1}-12"
    return f"{today.year}-{today.month - 1:02d}"


class BudgetPreparer(BasePreparer):
    def prepare(self, input: str, env: dict, user: dict) -> dict:
        return {"month": input.strip() or prev_month()}


class ComputeBudgetUseCase(BaseUseCase):
    def __init__(self, compute_budget):
        self._compute = compute_budget

    def execute(self, prepared: Any, env: dict, user: dict) -> Any:
        return self._compute.execute(prepared["month"])


def create_budget_controller(compute_budget) -> BaseController:
    return BaseController(BudgetPreparer(), ComputeBudgetUseCase(compute_budget))
