"""Invoice controllers."""

from __future__ import annotations

from typing import Any

from backend.brain.base_controller import BaseController, BasePreparer, BaseUseCase


class InvoicePreparer(BasePreparer):
    def prepare(self, input: str, env: dict, user: dict) -> dict:
        parts = input.strip().rsplit(maxsplit=1)
        if len(parts) == 2 and "-" in parts[1]:
            return {"contractor": parts[0], "month": parts[1]}
        return {"contractor": input.strip(), "month": None}


class GenerateInvoiceUseCase(BaseUseCase):
    def __init__(self, gen_invoice):
        self._gen = gen_invoice

    def execute(self, prepared: Any, env: dict, user: dict) -> Any:
        return self._gen.create_and_save(
            contractor=prepared["contractor"],
            month=prepared.get("month"),
            amount=prepared.get("amount", 0),
            articles=prepared.get("articles", []),
        )


def create_invoice_controller(gen_invoice) -> BaseController:
    return BaseController(InvoicePreparer(), GenerateInvoiceUseCase(gen_invoice))
