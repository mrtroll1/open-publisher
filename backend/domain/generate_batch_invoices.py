"""Use case: batch-generate invoices for all contractors in a month."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal

from common.models import (
    Contractor,
    Currency,
    GlobalContractor,
    IPContractor,
    Invoice,
    SamozanyatyContractor,
)
from backend.infrastructure.gateways.content_gateway import ContentGateway
from backend.infrastructure.repositories.budget_repo import read_all_amounts
from backend.infrastructure.repositories.invoice_repo import load_invoices
from backend.domain.generate_invoice import GenerateInvoice

logger = logging.getLogger(__name__)


@dataclass
class BatchResult:
    generated: list[tuple[bytes, Contractor, Invoice]] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=lambda: {"global": 0, "ip": 0, "samozanyaty": 0})
    errors: list[str] = field(default_factory=list)
    skipped: int = 0
    total: int = 0


class GenerateBatchInvoices:
    """Orchestrates batch invoice generation for all contractors."""

    def __init__(self):
        self._content = ContentGateway()
        self._gen = GenerateInvoice()

    def execute(
        self,
        contractors: list[Contractor],
        month: str,
        debug: bool = False,
        on_progress: callable = None,
    ) -> BatchResult:
        """Generate invoices for all contractors that have a budget entry and no existing invoice.

        Args:
            contractors: all known contractors
            month: e.g. "2026-01"
            debug: if True, skip invoice number increment and sheet save
            on_progress: optional callback(done, total) for progress updates
        """
        existing_invoices = load_invoices(month)
        already_generated = {inv.contractor_id for inv in existing_invoices}

        budget_amounts = read_all_amounts(month)
        if not budget_amounts:
            raise ValueError(f"Бюджетная таблица за {month} не найдена. Сначала выполните /budget.")

        # Filter to contractors that need invoices
        to_generate: list[tuple[Contractor, int]] = []
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
                to_generate.append((contractor, amount_int))

        result = BatchResult(total=len(to_generate))
        done = 0

        for contractor, amount_int in to_generate:
            amount = Decimal(str(amount_int))

            try:
                articles = self._content.fetch_articles(contractor, month)
            except Exception as e:
                result.errors.append(f"{contractor.display_name}: ошибка API ({e})")
                done += 1
                if on_progress:
                    on_progress(done, result.total)
                continue

            try:
                inv_result = self._gen.create_and_save(
                    contractor, month, amount, articles, debug=debug,
                )
            except Exception as e:
                result.errors.append(f"{contractor.display_name}: ошибка генерации ({e})")
                logger.exception("Generate failed for %s", contractor.display_name)
                done += 1
                if on_progress:
                    on_progress(done, result.total)
                continue

            if isinstance(contractor, GlobalContractor):
                result.counts["global"] += 1
            elif isinstance(contractor, SamozanyatyContractor):
                result.counts["samozanyaty"] += 1
            elif isinstance(contractor, IPContractor):
                result.counts["ip"] += 1

            result.generated.append((inv_result.pdf_bytes, contractor, inv_result.invoice))
            done += 1
            if on_progress:
                on_progress(done, result.total)

        return result
