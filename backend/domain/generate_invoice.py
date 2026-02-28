"""Use case: generate an invoice PDF for a contractor."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from common.config import (
    TEMPLATE_GLOBAL_ID,
    TEMPLATE_GLOBAL_PHOTO_ID,
    TEMPLATE_IP_ID,
    TEMPLATE_IP_PHOTO_ID,
    TEMPLATE_SAMOZANYATY_ID,
    TEMPLATE_SAMOZANYATY_PHOTO_ID,
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
from backend.infrastructure.repositories.contractor_repo import increment_invoice_number
from backend.infrastructure.repositories.invoice_repo import save_invoice

logger = logging.getLogger(__name__)


@dataclass
class InvoiceResult:
    pdf_bytes: bytes
    invoice: Invoice


class GenerateInvoice:
    """Orchestrates the full invoice generation flow."""

    def __init__(self):
        self._docs = DocsGateway()
        self._drive = DriveGateway()

    def create_and_save(
        self,
        contractor: Contractor,
        month: str,
        amount: Decimal,
        articles: list[ArticleEntry],
        invoice_date: date | None = None,
        debug: bool = False,
    ) -> InvoiceResult:
        """Full invoice flow: increment number, generate PDF, upload, save.

        In debug mode, skips number increment and sheet save.
        """
        if invoice_date is None:
            invoice_date = date.today()

        # 1. Increment invoice number (skip in debug)
        if not debug and contractor.currency == Currency.RUB:
            invoice_number = increment_invoice_number(contractor.id)
        else:
            invoice_number = 0

        # 2. Build invoice model
        invoice = Invoice(
            contractor_id=contractor.id,
            invoice_number=invoice_number,
            month=month,
            amount=amount,
            currency=contractor.currency,
            article_ids=[a.article_id for a in articles],
            status=InvoiceStatus.DRAFT,
        )

        # 3. Generate PDF
        pdf_bytes, doc_id = self._generate_pdf(contractor, invoice, articles, invoice_date)
        invoice.doc_id = doc_id

        # 4. Upload to Google Drive
        filename = f"{contractor.display_name}+Unsigned.pdf"
        try:
            gdrive_link = self._drive.upload_invoice_pdf(
                contractor, month, filename, pdf_bytes,
            )
        except Exception:
            logger.exception("Drive upload failed for %s", contractor.display_name)
            gdrive_link = ""
        invoice.gdrive_path = gdrive_link

        # 5. Save to invoices sheet
        save_invoice(invoice)

        return InvoiceResult(pdf_bytes=pdf_bytes, invoice=invoice)

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
        template = TEMPLATE_GLOBAL_PHOTO_ID if contractor.is_photographer else TEMPLATE_GLOBAL_ID
        doc_id = self._docs.copy_template(template, title, folder_id)

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
        template = TEMPLATE_IP_PHOTO_ID if contractor.is_photographer else TEMPLATE_IP_ID
        doc_id = self._docs.copy_template(template, title, folder_id)

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
        template = TEMPLATE_SAMOZANYATY_PHOTO_ID if contractor.is_photographer else TEMPLATE_SAMOZANYATY_ID
        doc_id = self._docs.copy_template(template, title, folder_id)

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
