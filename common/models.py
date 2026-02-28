"""Pydantic data models for contractors, invoices, and bank transactions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import ClassVar, Optional, Union

from pydantic import BaseModel, Field


class ContractorType(str, Enum):
    SAMOZANYATY = "самозанятый"
    IP = "ИП"
    GLOBAL = "global"


class Currency(str, Enum):
    EUR = "EUR"
    RUB = "RUB"
    USD = "USD"


class RoleCode(str, Enum):
    AUTHOR = "A"
    REDAKTOR = "R"
    KORREKTOR = "K"


class InvoiceStatus(str, Enum):
    DRAFT = "draft"
    SENT = "sent"
    SIGNED = "signed"
    PAID = "paid"


@dataclass(frozen=True)
class FieldMeta:
    """Metadata for a user-facing contractor field."""
    label: str
    required: bool = False


class Contractor(BaseModel):
    """Base contractor with fields common to all types."""

    # Class-level metadata (overridden by subclasses)
    SHEET_COLUMNS: ClassVar[list[str]] = []
    FIELD_META: ClassVar[dict[str, FieldMeta]] = {}

    id: str
    aliases: list[str] = Field(default_factory=list)
    role_code: RoleCode = RoleCode.AUTHOR
    is_photographer: bool = False
    email: str
    bank_name: str
    bank_account: str
    mags: str = ""
    invoice_number: int = 0
    telegram: str = ""
    secret_code: str = ""

    @property
    def type(self) -> ContractorType:
        raise NotImplementedError("Subclasses must define type")

    @property
    def currency(self) -> Currency:
        raise NotImplementedError("Subclasses must define currency")

    @property
    def display_name(self) -> str:
        return self.id

    @property
    def all_names(self) -> list[str]:
        return list(self.aliases)

    @classmethod
    def required_fields(cls) -> dict[str, str]:
        """Return {field_name: label} for fields required at registration."""
        return {k: v.label for k, v in cls.FIELD_META.items() if v.required}

    @classmethod
    def all_field_labels(cls) -> dict[str, str]:
        """Return {field_name: label} for all user-facing fields."""
        return {k: v.label for k, v in cls.FIELD_META.items()}

    @classmethod
    def field_names_csv(cls) -> str:
        """Comma-separated field names for LLM prompts."""
        return ", ".join(cls.FIELD_META.keys())


class GlobalContractor(Contractor):
    """International contractor (EUR/USD)."""
    name_en: str
    address: str
    swift: str

    SHEET_COLUMNS: ClassVar[list[str]] = [
        "id", "name_en", "aliases", "role_code",
        "email", "address",
        "bank_name", "bank_account", "swift",
        "mags", "telegram", "secret_code",
    ]

    FIELD_META: ClassVar[dict[str, FieldMeta]] = {
        "name_en": FieldMeta("полное имя (латиницей)", required=True),
        "address": FieldMeta("адрес", required=True),
        "email": FieldMeta("email"),
        "bank_name": FieldMeta("название банка", required=True),
        "bank_account": FieldMeta("IBAN / номер счёта", required=True),
        "swift": FieldMeta("BIC/SWIFT", required=True),
    }

    @property
    def type(self) -> ContractorType:
        return ContractorType.GLOBAL

    @property
    def currency(self) -> Currency:
        return Currency.EUR

    @property
    def display_name(self) -> str:
        return self.name_en or self.id

    @property
    def all_names(self) -> list[str]:
        names = []
        if self.name_en:
            names.append(self.name_en)
        names.extend(self.aliases)
        return names


class IPContractor(Contractor):
    """ИП — Individual Entrepreneur (RUB)."""
    name_ru: str
    passport_series: str
    passport_number: str
    passport_issued_by: str
    passport_issued_date: str
    passport_code: str
    ogrnip: str
    bik: str
    corr_account: str

    SHEET_COLUMNS: ClassVar[list[str]] = [
        "id", "name_ru", "aliases", "role_code",
        "email",
        "passport_series", "passport_number",
        "passport_issued_by", "passport_issued_date", "passport_code",
        "ogrnip",
        "bank_name", "bank_account", "bik", "corr_account",
        "mags", "invoice_number", "telegram", "secret_code",
    ]

    FIELD_META: ClassVar[dict[str, FieldMeta]] = {
        "name_ru": FieldMeta("ФИО", required=True),
        "ogrnip": FieldMeta("ОГРНИП", required=True),
        "passport_series": FieldMeta("серия паспорта", required=True),
        "passport_number": FieldMeta("номер паспорта", required=True),
        "passport_issued_by": FieldMeta("кем выдан паспорт", required=True),
        "passport_issued_date": FieldMeta("дата выдачи паспорта", required=True),
        "passport_code": FieldMeta("код подразделения", required=True),
        "email": FieldMeta("email", required=True),
        "bank_name": FieldMeta("банк", required=True),
        "bank_account": FieldMeta("номер счёта", required=True),
        "bik": FieldMeta("БИК", required=True),
        "corr_account": FieldMeta("корр. счёт", required=True),
    }

    @property
    def type(self) -> ContractorType:
        return ContractorType.IP

    @property
    def currency(self) -> Currency:
        return Currency.RUB

    @property
    def display_name(self) -> str:
        return self.name_ru or self.id

    @property
    def all_names(self) -> list[str]:
        names = []
        if self.name_ru:
            names.append(self.name_ru)
        names.extend(self.aliases)
        return names


class SamozanyatyContractor(Contractor):
    """Самозанятый — Self-employed (RUB)."""
    name_ru: str
    address: str
    passport_series: str
    passport_number: str
    inn: str
    bik: str
    corr_account: str

    SHEET_COLUMNS: ClassVar[list[str]] = [
        "id", "name_ru", "aliases", "role_code",
        "email", "address",
        "passport_series", "passport_number",
        "inn",
        "bank_name", "bank_account", "bik", "corr_account",
        "mags", "invoice_number", "telegram", "secret_code",
    ]

    FIELD_META: ClassVar[dict[str, FieldMeta]] = {
        "name_ru": FieldMeta("ФИО", required=True),
        "passport_series": FieldMeta("серия паспорта", required=True),
        "passport_number": FieldMeta("номер паспорта", required=True),
        "inn": FieldMeta("ИНН", required=True),
        "address": FieldMeta("адрес", required=True),
        "email": FieldMeta("email", required=True),
        "bank_name": FieldMeta("банк", required=True),
        "bank_account": FieldMeta("номер счёта", required=True),
        "bik": FieldMeta("БИК", required=True),
        "corr_account": FieldMeta("корр. счёт", required=True),
    }

    @property
    def type(self) -> ContractorType:
        return ContractorType.SAMOZANYATY

    @property
    def currency(self) -> Currency:
        return Currency.RUB

    @property
    def display_name(self) -> str:
        return self.name_ru or self.id

    @property
    def all_names(self) -> list[str]:
        names = []
        if self.name_ru:
            names.append(self.name_ru)
        names.extend(self.aliases)
        return names


AnyContractor = Union[GlobalContractor, IPContractor, SamozanyatyContractor]

# Map ContractorType enum → subclass for construction
CONTRACTOR_CLASS_BY_TYPE: dict[ContractorType, type[Contractor]] = {
    ContractorType.GLOBAL: GlobalContractor,
    ContractorType.IP: IPContractor,
    ContractorType.SAMOZANYATY: SamozanyatyContractor,
}


class Invoice(BaseModel):
    contractor_id: str
    invoice_number: int
    month: str  # "2026-01"
    amount: Decimal
    currency: Currency
    article_ids: list[str] = Field(default_factory=list)
    status: InvoiceStatus = InvoiceStatus.DRAFT
    gdrive_path: str = ""
    doc_id: str = ""
    legium_link: str = ""


class ArticleEntry(BaseModel):
    """A single article in an invoice annex."""
    article_id: str
    role_code: RoleCode = RoleCode.AUTHOR
    language: str = "Russian"


class BankTransaction(BaseModel):
    """A row from the Wio Bank CSV."""
    date: date
    ref_number: str = ""
    description: str = ""
    amount: Decimal = Decimal("0")
    balance: Decimal = Decimal("0")
    transaction_type: str = ""  # Transfers, Card, Fees
    original_ref: str = ""
    notes: str = ""


class IncomingEmail(BaseModel):
    """An email fetched from the support inbox."""
    uid: str
    from_addr: str
    to_addr: str = ""
    reply_to: str = ""
    subject: str
    body: str
    date: str
    message_id: str = ""


class SupportDraft(BaseModel):
    """A drafted reply to a support email, pending admin approval."""
    email: IncomingEmail
    can_answer: bool
    draft_reply: str


class AirtableExpense(BaseModel):
    """A row to be pushed to the Airtable expenses table."""
    id: Optional[int] = None
    payed: str = ""  # date string ISO format (YYYY-MM-DD)
    amount_rub: float = 0.0  # numeric amount in RUB
    contractor: str = ""
    unit: str = ""
    entity: str = ""
    description: str = ""
    group: str = ""
    parent: str = ""
    splited: str = ""
    comment: str = ""
    created_at: str = ""  # date string, set when uploading


