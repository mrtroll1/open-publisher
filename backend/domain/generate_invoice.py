"""Use case: generate an invoice PDF for a contractor."""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from common.config import (
    BUDGET_SHEETS_FOLDER_ID,
    TEMPLATE_GLOBAL_ID,
    TEMPLATE_IP_ID,
    TEMPLATE_SAMOZANYATY_ID,
)
from common.models import (
    ArticleEntry,
    Contractor,
    Currency,
    GlobalContractor,
    IPContractor,
    Invoice,
    InvoiceStatus,
    SamozanyatyContractor,
)
from backend.infrastructure.gateways.docs_gateway import DocsGateway
from backend.infrastructure.gateways.drive_gateway import DriveGateway
from backend.infrastructure.gateways.content_gateway import ContentGateway
from backend.infrastructure.gateways.sheets_gateway import SheetsGateway
from backend.infrastructure.repositories.contractor_repo import increment_invoice_number

logger = logging.getLogger(__name__)


def lookup_budget_amount(
    contractor: Contractor, month: str,
    drive: DriveGateway | None = None,
    sheets: SheetsGateway | None = None,
) -> int | None:
    """Look up contractor's amount from the Payments-for-{month} budget sheet.

    Returns the integer amount or None if not found.
    """
    if drive is None:
        drive = DriveGateway()
    if sheets is None:
        sheets = SheetsGateway()

    sheet_name = f"Payments-for-{month}"
    sheet_id = drive.find_file_by_name(sheet_name, BUDGET_SHEETS_FOLDER_ID)
    if not sheet_id:
        logger.info("Budget sheet not found: %s", sheet_name)
        return None

    rows = sheets.read(sheet_id, "A2:D200")
    name_lower = contractor.display_name.lower().strip()
    for row in rows:
        if len(row) >= 1 and row[0].strip().lower() == name_lower:
            eur = _parse_int(row[2]) if len(row) > 2 else 0
            rub = _parse_int(row[3]) if len(row) > 3 else 0
            amount = eur if contractor.currency == Currency.EUR else rub
            if amount:
                logger.info("Budget lookup for %s: %d", contractor.display_name, amount)
                return amount
    logger.info("Contractor %s not found in budget sheet %s", contractor.display_name, sheet_name)
    return None


def _parse_int(val: str) -> int:
    try:
        return int(val.strip()) if val.strip() else 0
    except ValueError:
        return 0


class GenerateInvoice:
    """Orchestrates the full invoice generation flow."""

    def __init__(self):
        self._docs = DocsGateway()
        self._drive = DriveGateway()
        self._content = ContentGateway()
        self._sheets = SheetsGateway()

    def execute(
        self,
        contractor: Contractor,
        month: str,
        amount: Decimal | None = None,
        invoice_date: date | None = None,
    ) -> tuple[bytes, str]:
        """Generate an invoice PDF.

        Returns (pdf_bytes, google_doc_id).
        """
        if invoice_date is None:
            invoice_date = date.today()

        # 1. Fetch articles (needed for PDF article table)
        articles = self._content.fetch_articles(contractor, month)

        # 2. Resolve amount: explicit > budget sheet
        if amount is None:
            budget_amount = lookup_budget_amount(
                contractor, month, self._drive, self._sheets,
            )
            if budget_amount is not None:
                amount = Decimal(str(budget_amount))
            else:
                logger.warning(
                    "No budget sheet amount for %s — cannot determine amount",
                    contractor.display_name,
                )
                raise ValueError(
                    f"Budget sheet for {month} not found or {contractor.display_name} "
                    f"not listed. Generate the budget first."
                )

        # 3. Increment invoice number (only for RUB contractors)
        if contractor.currency == Currency.RUB:
            new_invoice_number = increment_invoice_number(contractor.id)
        else:
            new_invoice_number = 0

        # 4. Build invoice model
        invoice = Invoice(
            contractor_id=contractor.id,
            invoice_number=new_invoice_number,
            month=month,
            amount=amount,
            currency=contractor.currency,
            article_ids=[a.article_id for a in articles],
            status=InvoiceStatus.DRAFT,
        )

        # 5. Generate PDF
        return self._generate_pdf(contractor, invoice, articles, invoice_date)

    def _generate_pdf(
        self,
        contractor: Contractor,
        invoice: Invoice,
        articles: list[ArticleEntry],
        invoice_date: date,
    ) -> tuple[bytes, str]:
        """Generate the actual PDF via Google Docs templates."""
        folder_id = self._drive.get_contractor_folder(contractor, invoice.month)

        if isinstance(contractor, IPContractor):
            return self._generate_ip(contractor, invoice, articles, invoice_date, folder_id)
        elif isinstance(contractor, SamozanyatyContractor):
            return self._generate_samozanyaty(contractor, invoice, articles, invoice_date, folder_id)
        elif isinstance(contractor, GlobalContractor):
            return self._generate_global(contractor, invoice, articles, invoice_date, folder_id)
        else:
            raise ValueError(f"Unknown contractor type: {type(contractor)}")

    def _generate_global(
        self, contractor: GlobalContractor, invoice: Invoice,
        articles: list[ArticleEntry], invoice_date: date, folder_id: str,
    ) -> tuple[bytes, str]:
        title = f"{contractor.name_en}+Unsigned"
        doc_id = self._docs.copy_template(TEMPLATE_GLOBAL_ID, title, folder_id)

        replacements = {
            "{{INVOICE_DATE}}": DocsGateway.format_date_en(invoice_date),
            "{{NAME}}": contractor.name_en,
            "{{ADDRESS}}": contractor.address,
            "{{BANK}}": contractor.bank_name,
            "{{IBAN}}": contractor.bank_account,
            "{{BIC_SWIFT}}": contractor.swift,
            "{{NUM_ARTICLES}}": str(len(articles)),
            "{{AMOUNT}}": f"{invoice.amount:.2f}",
            "{{CURRENCY}}": invoice.currency.value,
        }
        self._docs.replace_text(doc_id, replacements)
        self._docs.insert_articles_table(doc_id, "{{ARTICLES_TABLE}}", articles, ["№", "Article - Code", "Language"], "Russian")
        pdf = self._docs.export_pdf(doc_id)
        logger.info("Generated Global invoice for %s: %d bytes", contractor.display_name, len(pdf))
        return pdf, doc_id

    def _generate_ip(
        self, contractor: IPContractor, invoice: Invoice,
        articles: list[ArticleEntry], invoice_date: date, folder_id: str,
    ) -> tuple[bytes, str]:
        title = f"СчетОферта_ИП_{contractor.name_ru}_{invoice.month}"
        doc_id = self._docs.copy_template(TEMPLATE_IP_ID, title, folder_id)

        date_ru = DocsGateway.format_date_ru(invoice_date)
        replacements = {
            "{{FULL_NAME}}": contractor.name_ru,
            "{{OGRNIP}}": contractor.ogrnip,
            "{{PASSPORT_SERIES}}": contractor.passport_series,
            "{{PASSPORT_NUMBER}}": contractor.passport_number,
            "{{PASSPORT_ISSUED_BY}}": contractor.passport_issued_by,
            "{{PASSPORT_ISSUED_DATE}}": contractor.passport_issued_date,
            "{{PASSPORT_CODE}}": contractor.passport_code,
            "{{EMAIL}}": contractor.email,
            "{{BANK_ACCOUNT}}": contractor.bank_account,
            "{{BANK_NAME}}": contractor.bank_name,
            "{{BIK}}": contractor.bik,
            "{{CORR_ACCOUNT}}": contractor.corr_account,
            "{{AMOUNT}}": str(int(invoice.amount)),
            "{{INVOICE_NUMBER}}": str(invoice.invoice_number),
            "{{INVOICE_DATE}}": date_ru,
            "{{INVOICE_DAY}}": f"{invoice_date.day:02d}",
            "{{INVOICE_MONTH}}": date_ru.split("» ")[1].split(" ")[0],
            "{{INVOICE_YEAR}}": str(invoice_date.year),
        }
        self._docs.replace_text(doc_id, replacements)
        self._docs.insert_articles_table(doc_id, "{{ARTICLES_TABLE}}", articles, ["№", "Статья - Код", "Тип Произведения"], "Статья")
        pdf = self._docs.export_pdf(doc_id)
        logger.info("Generated ИП invoice for %s: %d bytes", contractor.display_name, len(pdf))
        return pdf, doc_id

    def _generate_samozanyaty(
        self, contractor: SamozanyatyContractor, invoice: Invoice,
        articles: list[ArticleEntry], invoice_date: date, folder_id: str,
    ) -> tuple[bytes, str]:
        title = f"СчетОферта_СЗ_{contractor.name_ru}_{invoice.month}"
        doc_id = self._docs.copy_template(TEMPLATE_SAMOZANYATY_ID, title, folder_id)

        date_ru = DocsGateway.format_date_ru(invoice_date)
        replacements = {
            "{{FULL_NAME}}": contractor.name_ru,
            "{{PASSPORT_SERIES}}": contractor.passport_series,
            "{{PASSPORT_NUMBER}}": contractor.passport_number,
            "{{INN}}": contractor.inn,
            "{{ADDRESS}}": contractor.address,
            "{{EMAIL}}": contractor.email,
            "{{BANK_ACCOUNT}}": contractor.bank_account,
            "{{BANK_NAME}}": contractor.bank_name,
            "{{BIK}}": contractor.bik,
            "{{CORR_ACCOUNT}}": contractor.corr_account,
            "{{AMOUNT}}": str(int(invoice.amount)),
            "{{INVOICE_NUMBER}}": str(invoice.invoice_number),
            "{{INVOICE_DATE}}": date_ru,
            "{{INVOICE_DAY}}": f"{invoice_date.day:02d}",
            "{{INVOICE_MONTH}}": date_ru.split("» ")[1].split(" ")[0],
            "{{INVOICE_YEAR}}": str(invoice_date.year),
        }
        self._docs.replace_text(doc_id, replacements)
        self._docs.insert_articles_table(doc_id, "{{ARTICLES_TABLE}}", articles, ["№", "Статья - Код", "Тип Произведения"], "Статья")
        pdf = self._docs.export_pdf(doc_id)
        logger.info("Generated Самозанятый invoice for %s: %d bytes", contractor.display_name, len(pdf))
        return pdf, doc_id
