"""Use case: batch-generate invoices for all contractors in a month."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal

from backend.commands.invoice.generate import GenerateInvoice
from backend.infrastructure.gateways.republic_gateway import RepublicGateway
from backend.infrastructure.repositories.sheets.budget_repo import load_all_amounts
from backend.infrastructure.repositories.sheets.invoice_repo import load_invoices
from backend.models import (
    Contractor,
    ContractorType,
    Currency,
    Invoice,
)

logger = logging.getLogger(__name__)


@dataclass
class BatchResult:
    generated: list[tuple[bytes, Contractor, Invoice]] = field(default_factory=list)
    counts: dict[ContractorType, int] = field(
        default_factory=lambda: {t: 0 for t in ContractorType}
    )
    errors: list[str] = field(default_factory=list)
    skipped: int = 0
    total: int = 0


class GenerateBatchInvoices:
    """Orchestrates batch invoice generation for all contractors."""

    def __init__(self, republic_gw: RepublicGateway | None = None, gen_invoice: GenerateInvoice | None = None):
        self._content = republic_gw or RepublicGateway()
        self._gen = gen_invoice or GenerateInvoice()

    def execute(
        self,
        contractors: list[Contractor],
        month: str,
        *,
        debug: bool = False,
        on_progress: callable | None = None,
    ) -> BatchResult:
        """Generate invoices for all contractors that have a budget entry and no existing invoice."""
        to_generate = self._pending_contractors(contractors, month)
        result = BatchResult(total=len(to_generate))
        done = 0

        for contractor, amount_int in to_generate:
            try:
                self._generate_one(contractor, month, amount_int, result, debug=debug)
            finally:
                done += 1
                if on_progress:
                    on_progress(done, result.total)

        return result

    @staticmethod
    def _pending_contractors(
        contractors: list[Contractor], month: str,
    ) -> list[tuple[Contractor, int]]:
        """Filter to contractors that need invoices this month."""
        already_generated = {inv.contractor_id for inv in load_invoices(month)}
        budget_amounts = load_all_amounts(month)
        if not budget_amounts:
            raise ValueError(f"Бюджетная таблица за {month} не найдена. Сначала выполните /budget.")

        pending: list[tuple[Contractor, int]] = []
        for contractor in contractors:
            if contractor.id in already_generated:
                continue
            name_lower = contractor.display_name.lower().strip()
            budget_entry = budget_amounts.get(name_lower)
            if not budget_entry:
                continue
            eur, rub, _note = budget_entry
            amount_int = eur if contractor.currency == Currency.EUR else rub
            if amount_int:
                pending.append((contractor, amount_int))
        return pending

    def _generate_one(
        self, contractor: Contractor, month: str, amount_int: int,
        result: BatchResult, *, debug: bool,
    ) -> None:
        """Generate a single invoice, updating result in place."""
        try:
            articles = self._content.fetch_articles(contractor, month)
        except Exception as e:
            result.errors.append(f"{contractor.display_name}: ошибка API ({e})")
            return

        try:
            inv_result = self._gen.create_and_save(
                contractor, month, Decimal(str(amount_int)), articles, debug=debug,
            )
        except Exception as e:
            result.errors.append(f"{contractor.display_name}: ошибка генерации ({e})")
            logger.exception("Generate failed for %s", contractor.display_name)
            return

        result.counts[contractor.type] += 1

        result.generated.append((inv_result.pdf_bytes, contractor, inv_result.invoice))
