"""Backend facade — re-exports everything the telegram bot needs."""

import json
import time

# --- Contractor repository (module-level functions) ---
# --- Gateways (exposed as module-level convenience functions) ---
from backend.brain.prompt_loader import load_template
from backend.commands.budget.redirect import redirect_in_budget as _redirect_impl
from backend.commands.budget.redirect import unredirect_in_budget as _unredirect_impl
from backend.config import GEMINI_MODEL_FAST
from backend.infrastructure.gateways.docs_gateway import DocsGateway
from backend.infrastructure.gateways.drive_gateway import DriveGateway as _DriveGateway
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway as _GeminiGateway
from backend.infrastructure.gateways.republic_gateway import RepublicGateway as _RepublicGateway
from backend.infrastructure.memory.retriever import KnowledgeRetriever
from backend.infrastructure.repositories.postgres import DbGateway
from backend.infrastructure.repositories.sheets.budget_repo import load_all_amounts
from backend.infrastructure.repositories.sheets.contractor_repo import (
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

# --- Invoice repository ---
from backend.infrastructure.repositories.sheets.invoice_repo import (
    delete_invoice,
    load_invoices,
    save_invoice,
    update_invoice_status,
    update_legium_link,
)

# --- Rules repository ---
from backend.infrastructure.repositories.sheets.rules_repo import (
    add_redirect_rule,
    find_redirect_rules_by_target,
    remove_redirect_rule,
)

_drive = _DriveGateway()
_gemini = _GeminiGateway()
_content = _RepublicGateway()
_retriever = KnowledgeRetriever()


def fetch_articles(contractor, month):
    """Fetch articles for a contractor from the content API."""
    return _content.fetch_articles(contractor, month)


def fetch_articles_by_name(author: str, month: str) -> list[int]:
    """Check if an author name has articles for the given month."""
    return _content.fetch_articles_by_name(author, month)


def parse_contractor_data(text: str, fields_csv: str, context: str = "") -> dict:
    """Parse contractor data from free-form text using LLM."""
    r = _retriever
    knowledge = r.get_domain_context("contractor") + "\n\n" + r.retrieve_full_domain("contractor")
    prompt = load_template("contractor/contractor-parse.md", {
        "FIELDS": fields_csv,
        "CONTEXT": context,
        "INPUT": text,
    })
    if knowledge:
        prompt = knowledge + "\n\n" + prompt
    return _gemini.call(prompt)


def translate_name_to_russian(name_en: str) -> str:
    """Translate a name to Russian."""
    prompt = load_template("contractor/translate-name.md", {"NAME": name_en})
    t0 = time.time()
    result = _gemini.call(prompt)
    latency_ms = int((time.time() - t0) * 1000)
    DbGateway().save_message(
        text=prompt, type="system",
        metadata={"task": "TRANSLATE_NAME", "model": GEMINI_MODEL_FAST,
                  "result": json.dumps(result), "latency_ms": latency_ms},
    )
    return result.get("translated_name", "")


def upload_invoice_pdf(contractor, month, filename, pdf_bytes):
    """Upload an invoice PDF and return a shareable link."""
    return _drive.upload_invoice_pdf(contractor, month, filename, pdf_bytes)


def load_budget_amounts(month: str) -> dict:
    """Read budget sheet for a month. Returns {name_lower: (eur, rub, note)}."""
    return load_all_amounts(month)


def redirect_in_budget(source_name: str, target, month: str) -> None:
    _redirect_impl(source_name, target, month)


def unredirect_in_budget(source_name: str, target, month: str) -> None:
    _unredirect_impl(source_name, target, month)


def create_and_save_invoice(contractor, month, amount, articles, *, invoice_date=None, debug=False):  # noqa: PLR0913
    return GenerateInvoice().create_and_save(
        contractor, month, amount, articles, invoice_date, debug,
    )


def export_pdf(doc_id: str) -> bytes:
    return DocsGateway().export_pdf(doc_id)


# --- Contractor service ---
from backend.commands.bank.parse_statement import ParseBankStatement
from backend.commands.budget.compute import ComputeBudget
from backend.commands.check_health import format_healthcheck_results
from backend.commands.contractor.create import (
    check_registration_complete,
    create_contractor,
)
from backend.commands.contractor.registration import (
    parse_registration_data,
    translate_contractor_name,
)

# --- Domain helpers ---
from backend.commands.contractor.validate import validate_fields as validate_contractor_fields
from backend.commands.draft_support import TechSupportHandler
from backend.commands.invoice.batch import BatchResult, GenerateBatchInvoices

# --- Use cases ---
from backend.commands.invoice.generate import GenerateInvoice, InvoiceResult
from backend.commands.invoice.prepare import prepare_existing_invoice
from backend.commands.invoice.resolve_amount import plural_ru, resolve_amount

# --- Invoice service ---
from backend.commands.invoice.service import (
    DeliveryAction,
    ExistingInvoiceResult,
    NewInvoiceData,
    get_invoice_folder_path,
    prepare_new_invoice_data,
    resolve_existing_invoice,
)
from backend.commands.run_code import run_claude_code
