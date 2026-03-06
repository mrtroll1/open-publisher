"""Bank controller — bank statement parsing."""

from __future__ import annotations

from backend.brain.base_controller import BaseController, BasePreparer
from backend.commands.bank import ParseBankStatementUseCase


class BankPreparer(BasePreparer):
    def prepare(self, input: str, env: dict, user: dict) -> dict:
        return {"filepath": input.strip()}


class BankController(BaseController):
    def __init__(self, parser):
        super().__init__(BankPreparer(), ParseBankStatementUseCase(parser))
