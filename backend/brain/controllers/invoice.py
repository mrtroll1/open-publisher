"""Invoice controller — invoice generation."""

from __future__ import annotations

from backend.brain.base_controller import BaseController, BasePreparer
from backend.commands.invoice import GenerateInvoiceUseCase


class InvoicePreparer(BasePreparer):
    def prepare(self, input: str, env: dict, user: dict) -> dict:
        parts = input.strip().rsplit(maxsplit=1)
        if len(parts) == 2 and "-" in parts[1]:
            return {"contractor": parts[0], "month": parts[1]}
        return {"contractor": input.strip(), "month": None}


class InvoiceController(BaseController):
    def __init__(self, gen_invoice):
        super().__init__(InvoicePreparer(), GenerateInvoiceUseCase(gen_invoice))
