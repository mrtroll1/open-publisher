"""Invoice — generation and batch processing."""

from __future__ import annotations

from typing import Any


class GenerateInvoiceUseCase:
    def __init__(self, gen_invoice):
        self._gen = gen_invoice

    def execute(self, prepared: Any, _env: dict, _user: dict) -> Any:
        return self._gen.create_and_save(
            contractor=prepared["contractor"],
            month=prepared.get("month"),
            amount=prepared.get("amount", 0),
            articles=prepared.get("articles", []),
        )
