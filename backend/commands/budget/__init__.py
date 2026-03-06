"""Budget — computation and reporting."""

from __future__ import annotations

from typing import Any

from backend.brain.base_controller import BaseUseCase


class ComputeBudgetUseCase(BaseUseCase):
    def __init__(self, compute_budget):
        self._compute = compute_budget

    def execute(self, prepared: Any, env: dict, user: dict) -> Any:
        return self._compute.execute(prepared["month"])
