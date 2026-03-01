"""Backend facade — re-exports everything the telegram bot needs."""

# --- Contractor repository (module-level functions) ---
from backend.infrastructure.repositories.contractor_repo import (  # noqa: F401
    bind_telegram_id,
    find_contractor,
    find_contractor_by_id,
    find_contractor_by_telegram_id,
    find_contractor_strict,
    fuzzy_find,
    increment_invoice_number,
    load_all_contractors,
    next_contractor_id,
    pop_random_secret_code,
    save_contractor,
    update_contractor_fields,
)

# --- Rules repository ---
from backend.infrastructure.repositories.rules_repo import (  # noqa: F401
    add_redirect_rule,
    find_redirect_rules_by_target,
    remove_redirect_rule,
)

# --- Invoice repository ---
from backend.infrastructure.repositories.invoice_repo import (  # noqa: F401
    delete_invoice,
    load_invoices,
    save_invoice,
    update_invoice_status,
    update_legium_link,
)

# --- Gateways (exposed as module-level convenience functions) ---
from backend.infrastructure.gateways.drive_gateway import DriveGateway as _DriveGateway
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway as _GeminiGateway
from backend.infrastructure.gateways.republic_gateway import RepublicGateway as _RepublicGateway

_drive = _DriveGateway()
_gemini = _GeminiGateway()
_content = _RepublicGateway()


def fetch_articles(contractor, month):
    """Fetch articles for a contractor from the content API."""
    return _content.fetch_articles(contractor, month)


def fetch_articles_by_name(author: str, month: str) -> list[int]:
    """Check if an author name has articles for the given month."""
    return _content.fetch_articles_by_name(author, month)


def parse_contractor_data(text: str, fields_csv: str, context: str = "") -> dict:
    """Parse contractor data from free-form text using LLM."""
    from backend.domain import compose_request
    prompt, model, _ = compose_request.contractor_parse(text, fields_csv, context)
    return _gemini.call(prompt, model)


def translate_name_to_russian(name_en: str) -> str:
    """Translate a name to Russian."""
    from backend.domain import compose_request
    prompt, model, _ = compose_request.translate_name(name_en)
    result = _gemini.call(prompt, model)
    return result.get("translated_name", "")


def upload_invoice_pdf(contractor, month, filename, pdf_bytes):
    """Upload an invoice PDF and return a shareable link."""
    return _drive.upload_invoice_pdf(contractor, month, filename, pdf_bytes)


def read_budget_amounts(month: str) -> dict:
    """Read budget sheet for a month. Returns {name_lower: (eur, rub, note)}."""
    from backend.infrastructure.repositories.budget_repo import read_all_amounts
    return read_all_amounts(month)


def redirect_in_budget(source_name: str, target, month: str) -> None:
    """Move source author's budget row into target contractor's row."""
    from backend.infrastructure.repositories.budget_repo import redirect_in_budget as _impl
    _impl(source_name, target, month)


def unredirect_in_budget(source_name: str, target, month: str) -> None:
    """Undo a redirect: restore source as standalone row."""
    from backend.infrastructure.repositories.budget_repo import unredirect_in_budget as _impl
    _impl(source_name, target, month)


def create_and_save_invoice(contractor, month, amount, articles, invoice_date=None, debug=False):
    """Full invoice flow: increment number, generate PDF, upload, save.

    Returns InvoiceResult(pdf_bytes, invoice).
    """
    from backend.domain.generate_invoice import GenerateInvoice
    return GenerateInvoice().create_and_save(
        contractor, month, amount, articles, invoice_date, debug,
    )


def export_pdf(doc_id: str) -> bytes:
    """Re-export a PDF from a Google Docs document ID."""
    from backend.infrastructure.gateways.docs_gateway import DocsGateway
    return DocsGateway().export_pdf(doc_id)


# --- Domain helpers ---
from backend.domain.validate_contractor import validate_fields as validate_contractor_fields  # noqa: F401
from backend.domain.resolve_amount import resolve_amount, plural_ru  # noqa: F401
from backend.domain.prepare_invoice import prepare_existing_invoice  # noqa: F401

# --- Use cases ---
from backend.domain.generate_invoice import GenerateInvoice, InvoiceResult  # noqa: F401
from backend.domain.generate_batch_invoices import GenerateBatchInvoices, BatchResult  # noqa: F401
from backend.domain.parse_bank_statement import ParseBankStatement  # noqa: F401
from backend.domain.compute_budget import ComputeBudget  # noqa: F401
from backend.domain.support_email_service import SupportEmailService  # noqa: F401
from backend.domain.article_proposal_service import ArticleProposalService  # noqa: F401
