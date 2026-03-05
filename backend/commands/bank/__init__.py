"""Bank statement controllers."""

from __future__ import annotations

from typing import Any

from backend.brain.base_controller import BaseController, BasePreparer, BaseUseCase


class BankPreparer(BasePreparer):
    def prepare(self, input: str, env: dict, user: dict) -> dict:
        return {"filepath": input.strip()}


class ParseBankStatementUseCase(BaseUseCase):
    def __init__(self, parser):
        self._parser = parser

    def execute(self, prepared: Any, env: dict, user: dict) -> Any:
        return self._parser.execute(prepared["filepath"], aed_to_rub=prepared.get("aed_to_rub", 1.0))


def create_bank_controller(parser) -> BaseController:
    return BaseController(BankPreparer(), ParseBankStatementUseCase(parser))
