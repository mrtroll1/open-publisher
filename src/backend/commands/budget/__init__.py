"""Budget — computation and reporting."""

from __future__ import annotations

from typing import Any


class ComputeBudgetUseCase:
    def __init__(self, compute_budget):
        self._compute = compute_budget

    def execute(self, prepared: Any, _env: dict, _user: dict) -> Any:
        return self._compute.execute(prepared["month"])
