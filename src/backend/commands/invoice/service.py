"""Invoice delivery and flow business logic."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from backend.commands.invoice.prepare import PreparedInvoice, prepare_existing_invoice
from backend.commands.invoice.resolve_amount import plural_ru, resolve_amount
from backend.config import DRIVE_FOLDER_GLOBAL, DRIVE_FOLDER_RU
from backend.infrastructure.gateways.republic_gateway import RepublicGateway
from backend.infrastructure.repositories.sheets.budget_repo import load_all_amounts
from backend.models import Currency, GlobalContractor, InvoiceStatus


class DeliveryAction(Enum):
    SEND_PROFORMA = auto()
    PROFORMA_ALREADY_SENT = auto()
    SEND_RUB_WITH_LEGIUM = auto()
    SEND_RUB_DRAFT = auto()
    RUB_ALREADY_SENT = auto()


@dataclass
class ExistingInvoiceResult:
    prepared: PreparedInvoice
    action: DeliveryAction


@dataclass
class NewInvoiceData:
    default_amount: int
    explanation: str
    article_ids: list[str]
    num_articles: int
    pub_word: str


class InvoiceService:
    def resolve_existing(self, contractor, month):
        prepared = prepare_existing_invoice(contractor, month)
        if not prepared:
            return None
        action = self._determine_action(contractor, prepared.invoice)
        return ExistingInvoiceResult(prepared=prepared, action=action)

    def prepare_new_data(self, contractor, month):
        budget_amounts = load_all_amounts(month)
        articles = RepublicGateway().fetch_articles(contractor, month)
        default_amount, explanation = resolve_amount(budget_amounts, contractor, len(articles))
        if not default_amount:
            return None
        return self._build_new_data(articles, default_amount, explanation)

    def folder_path(self, contractor, month):
        if isinstance(contractor, GlobalContractor):
            return DRIVE_FOLDER_GLOBAL, month, contractor.name_en.replace(" ", "")
        parts = month.split("-")
        month_folder = f"{parts[1]}-{parts[0]}" if len(parts) == 2 else month
        return DRIVE_FOLDER_RU, month_folder, contractor.display_name.replace(" ", "")

    def _determine_action(self, contractor, inv):
        if contractor.currency == Currency.EUR:
            return (DeliveryAction.SEND_PROFORMA if inv.status == InvoiceStatus.DRAFT
                    else DeliveryAction.PROFORMA_ALREADY_SENT)
        if inv.legium_link:
            return DeliveryAction.SEND_RUB_WITH_LEGIUM
        if inv.status == InvoiceStatus.DRAFT:
            return DeliveryAction.SEND_RUB_DRAFT
        return DeliveryAction.RUB_ALREADY_SENT

    def _build_new_data(self, articles, default_amount, explanation):
        num = len(articles)
        pub_word = plural_ru(num, "публикация", "публикации", "публикаций") if num else "0 публикаций"
        return NewInvoiceData(
            default_amount=default_amount, explanation=explanation,
            article_ids=[a.article_id for a in articles],
            num_articles=num, pub_word=pub_word,
        )
