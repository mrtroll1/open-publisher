"""Bank statement — parsing and processing."""

from __future__ import annotations

from typing import Any

from backend.brain.base_controller import BaseUseCase


class ParseBankStatementUseCase(BaseUseCase):
    def __init__(self, parser):
        self._parser = parser

    def execute(self, prepared: Any, _env: dict, _user: dict) -> Any:
        return self._parser.execute(prepared["filepath"], aed_to_rub=prepared.get("aed_to_rub", 1.0))
