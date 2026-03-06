"""Invoice delivery and flow business logic."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from backend import fetch_articles, read_budget_amounts
from backend.commands.invoice.resolve_amount import plural_ru, resolve_amount
from backend.commands.invoice.prepare import PreparedInvoice, prepare_existing_invoice
from backend.config import DRIVE_FOLDER_GLOBAL, DRIVE_FOLDER_RU
from backend.models import Contractor, Currency, GlobalContractor, InvoiceStatus


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


def resolve_existing_invoice(contractor: Contractor, month: str) -> ExistingInvoiceResult | None:
    prepared = prepare_existing_invoice(contractor, month)
    if not prepared:
        return None

    inv = prepared.invoice

    if contractor.currency == Currency.EUR:
        if inv.status == InvoiceStatus.DRAFT:
            action = DeliveryAction.SEND_PROFORMA
        else:
            action = DeliveryAction.PROFORMA_ALREADY_SENT
    else:
        if inv.legium_link:
            action = DeliveryAction.SEND_RUB_WITH_LEGIUM
        elif inv.status == InvoiceStatus.DRAFT:
            action = DeliveryAction.SEND_RUB_DRAFT
        else:
            action = DeliveryAction.RUB_ALREADY_SENT

    return ExistingInvoiceResult(prepared=prepared, action=action)


def prepare_new_invoice_data(contractor: Contractor, month: str) -> NewInvoiceData | None:
    budget_amounts = read_budget_amounts(month)
    articles = fetch_articles(contractor, month)
    num_articles = len(articles)

    default_amount, explanation = resolve_amount(budget_amounts, contractor, num_articles)
    if not default_amount:
        return None

    article_ids = [a.article_id for a in articles]
    pub_word = (
        plural_ru(num_articles, "публикация", "публикации", "публикаций")
        if num_articles
        else "0 публикаций"
    )

    return NewInvoiceData(
        default_amount=default_amount,
        explanation=explanation,
        article_ids=article_ids,
        num_articles=num_articles,
        pub_word=pub_word,
    )


def get_invoice_folder_path(contractor: Contractor, month: str) -> tuple[str, str, str]:
    if isinstance(contractor, GlobalContractor):
        parent = DRIVE_FOLDER_GLOBAL
        month_folder = month
        name_folder = contractor.name_en.replace(" ", "")
    else:
        parent = DRIVE_FOLDER_RU
        parts = month.split("-")
        month_folder = f"{parts[1]}-{parts[0]}" if len(parts) == 2 else month
        name_folder = contractor.display_name.replace(" ", "")
    return parent, month_folder, name_folder
