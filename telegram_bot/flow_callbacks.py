"""Callback functions for flow declarations.

Each handler receives (message, state) and returns Optional[str]:
  - None  = stay in current state (no transition)
  - "key" = follow the transition mapped to that key
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import tempfile
from decimal import Decimal
from aiogram import types
from aiogram.enums import ChatAction
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery

from typing import Callable

from common.config import ADMIN_TELEGRAM_IDS, BOT_USERNAME, EMAIL_ADDRESS

from common.models import (
    CONTRACTOR_CLASS_BY_TYPE,
    Contractor,
    ContractorType,
    Currency,
    EditorialItem,
    GlobalContractor,
    InvoiceStatus,
    RoleCode,
    SupportDraft,
)
from backend import (
    add_redirect_rule,
    bind_telegram_id,
    create_and_save_invoice,
    delete_invoice,
    export_pdf,
    redirect_in_budget,
    unredirect_in_budget,
    fetch_articles,
    find_contractor,
    find_contractor_by_id,
    find_contractor_by_telegram_id,
    find_redirect_rules_by_target,
    fuzzy_find,
    GenerateBatchInvoices,
    load_invoices,
    next_contractor_id,
    parse_contractor_data,
    plural_ru,
    pop_random_secret_code,
    prepare_existing_invoice,
    read_budget_amounts,
    remove_redirect_rule,
    resolve_amount,
    save_contractor,
    translate_name_to_russian,
    update_contractor_fields,
    update_invoice_status,
    update_legium_link,
    upload_invoice_pdf,
    validate_contractor_fields,
)
from telegram_bot import replies
from telegram_bot.bot_helpers import bot, get_contractors, is_admin, md_to_tg_html, prev_month
from backend.domain import compose_request
from backend.domain.compute_budget import ComputeBudget
from backend.domain.healthcheck import run_healthchecks, format_healthcheck_results
from backend.domain.inbox_service import InboxService
from backend.domain.parse_bank_statement import ParseBankStatement
from backend.domain.code_runner import run_claude_code
from backend.domain.command_classifier import CommandClassifier
from backend.infrastructure.gateways.db_gateway import DbGateway
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from backend.infrastructure.gateways.repo_gateway import RepoGateway
from telegram_bot.flow_dsl import GroupChatConfig

logger = logging.getLogger(__name__)

_db = DbGateway()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Shared helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def _safe_edit_text(message, text: str, **kwargs) -> None:
    try:
        await message.edit_text(text, **kwargs)
    except TelegramBadRequest:
        pass


async def _send_html(message: types.Message, text: str, **kwargs) -> None:
    """Send with markdown→HTML conversion; fall back to plain text on parse error."""
    try:
        await message.answer(md_to_tg_html(text), parse_mode="HTML", **kwargs)
    except TelegramBadRequest:
        await message.answer(text, **kwargs)


def _parse_flags(text: str) -> tuple[bool, bool, str]:
    """Parse -v (verbose) and -e (expert) flags. Returns (verbose, expert, rest)."""
    verbose = False
    expert = False
    while text:
        if text.startswith("-v ") or text.startswith("verbose "):
            verbose = True
            text = text.split(None, 1)[1] if " " in text else ""
        elif text.startswith("-e ") or text.startswith("expert "):
            expert = True
            text = text.split(None, 1)[1] if " " in text else ""
        else:
            break
    return verbose, expert, text


async def _find_contractor_or_suggest(
    raw_name: str, message: types.Message,
) -> Contractor | None:
    contractors = await get_contractors()
    contractor = find_contractor(raw_name, contractors)
    if contractor:
        return contractor
    matches = fuzzy_find(raw_name, contractors, threshold=0.4)
    if matches:
        suggestions = "\n".join(
            f"  - {c.display_name} ({c.type.value})" for c, _ in matches[:5]
        )
        await message.answer(replies.lookup.fuzzy_suggestions.format(suggestions=suggestions))
    else:
        await message.answer(replies.lookup.not_found)
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  /start
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _linked_menu_markup(contractor: Contractor) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=replies.linked_menu.btn_contract, callback_data="menu:contract")],
        [InlineKeyboardButton(text=replies.linked_menu.btn_update, callback_data="menu:update")],
    ]
    if contractor.role_code == RoleCode.REDAKTOR:
        rows.append([InlineKeyboardButton(
            text=replies.linked_menu.btn_editor_sources, callback_data="menu:editor",
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def handle_start(message: types.Message, state: FSMContext) -> None:
    await state.clear()
    if is_admin(message.from_user.id):
        await message.answer(replies.start.admin)
        return
    await message.answer(replies.start.contractor)


async def handle_menu(message: types.Message, state: FSMContext) -> None:
    await state.clear()
    if is_admin(message.from_user.id):
        await message.answer(replies.menu.admin)
        return
    contractors = await get_contractors()
    contractor = find_contractor_by_telegram_id(message.from_user.id, contractors)
    if contractor:
        await message.answer(
            replies.menu.prompt,
            reply_markup=_linked_menu_markup(contractor),
        )
        return
    await message.answer(replies.start.contractor)


async def _deliver_or_start_invoice(
    message: types.Message, state: FSMContext, contractor: Contractor,
) -> None:
    """Try delivering an existing invoice, or start the invoice flow."""
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    try:
        delivered = await _deliver_existing_invoice(message, contractor)
    except Exception:
        logger.exception("Invoice delivery failed for %s", contractor.display_name)
        await message.answer(replies.invoice.delivery_error)
        return
    if not delivered:
        result = await _start_invoice_flow(message, state, contractor)
        if result == "invoice":
            await state.set_state("ContractorStates:waiting_amount")
        else:
            await message.answer(
                replies.registration.no_articles.format(month=prev_month())
            )


async def handle_sign_doc(message: types.Message, state: FSMContext) -> None:
    await state.clear()
    contractors = await get_contractors()
    contractor = find_contractor_by_telegram_id(message.from_user.id, contractors)
    if not contractor:
        await message.answer(replies.start.contractor)
        return
    await _deliver_or_start_invoice(message, state, contractor)


async def handle_update_payment_data(message: types.Message, state: FSMContext) -> None:
    await state.clear()
    contractors = await get_contractors()
    contractor = find_contractor_by_telegram_id(message.from_user.id, contractors)
    if not contractor:
        await message.answer(replies.start.contractor)
        return
    await state.set_state("ContractorStates:waiting_update_data")
    await message.answer(replies.linked_menu.update_prompt)


async def handle_manage_redirects(message: types.Message, state: FSMContext) -> None:
    await state.clear()
    contractors = await get_contractors()
    contractor = find_contractor_by_telegram_id(message.from_user.id, contractors)
    if not contractor or contractor.role_code != RoleCode.REDAKTOR:
        await message.answer(replies.start.contractor)
        return
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    rules = await asyncio.to_thread(find_redirect_rules_by_target, contractor.id)
    text, markup = _editor_sources_content(rules)
    await message.answer(text, reply_markup=markup)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Contractor flow callbacks (lookup → registration → verification → invoice)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _dup_button_label(contractor: Contractor) -> str:
    """Format button text as 'alias (real_name)' for duplicate selection."""
    alias = contractor.aliases[0] if contractor.aliases else ""
    real = contractor.display_name
    if alias and alias != real:
        return f"{alias} ({real})"
    return real


async def handle_type_selection(message: types.Message, state: FSMContext) -> str | None:
    """Parse contractor type choice. Returns 'valid' or None (stay)."""
    text = message.text.strip().rstrip(".")
    type_map = {
        "1": ContractorType.SAMOZANYATY,
        "2": ContractorType.IP,
        "3": ContractorType.GLOBAL,
        "самозанятый": ContractorType.SAMOZANYATY,
        "ип": ContractorType.IP,
        "global": ContractorType.GLOBAL,
    }
    ctype = type_map.get(text.lower())
    if not ctype:
        await message.answer(replies.registration.type_invalid)
        return None

    data = await state.get_data()
    alias = data.get("alias", "")
    await state.set_data({
        "contractor_type": ctype.value,
        "collected_data": {"aliases": [alias]} if alias else {},
    })

    await message.answer(replies.registration.data_prompts[ctype])
    return "valid"


async def handle_data_input(message: types.Message, state: FSMContext) -> str | None:
    """Parse contractor data with LLM. Returns 'complete' or None (stay/loop)."""
    data = await state.get_data()
    ctype = ContractorType(data["contractor_type"])
    raw_text = message.text.strip()
    collected = data.get("collected_data", {})
    cls = CONTRACTOR_CLASS_BY_TYPE[ctype]

    prev_warnings = validate_contractor_fields(collected, ctype) if collected else []
    parsed = await _parse_with_llm(raw_text, ctype, collected, prev_warnings or None)
    if "parse_error" in parsed:
        await message.answer(replies.registration.parse_error)
        return None

    llm_comment = parsed.pop("comment", None)
    validation_id = parsed.pop("_validation_id", None)

    for key, value in parsed.items():
        if isinstance(value, str) and value.strip():
            collected[key] = value.strip()

    if validation_id:
        collected["_validation_id"] = validation_id

    all_fields = cls.all_field_labels()
    required = cls.required_fields()
    missing = {
        field: label
        for field, label in required.items()
        if not collected.get(field, "").strip()
    }
    warnings = validate_contractor_fields(collected, ctype)
    if llm_comment:
        warnings.append(llm_comment)

    if missing or warnings:
        await state.update_data(collected_data=collected)
        filled_lines = []
        for field, label in all_fields.items():
            val = collected.get(field, "")
            if val:
                filled_lines.append(f"  ✓ {label}: {val}")
        parts = [replies.registration.progress_header.format(filled="\n".join(filled_lines))]
        if missing:
            parts.append(replies.registration.still_needed.format(fields=", ".join(missing.values())))
        if warnings:
            parts.append("\n".join(f"  ⚠ {w}" for w in warnings))
        parts.append(replies.registration.send_corrections)
        await message.answer("\n\n".join(parts))
        return None

    # For Global contractors, translate name to Russian and add as alias
    if ctype == ContractorType.GLOBAL:
        name_en = collected.get("name_en", "")
        if name_en:
            name_ru = await asyncio.to_thread(translate_name_to_russian, name_en)
            if name_ru:
                aliases = collected.get("aliases", [])
                if name_ru not in aliases:
                    aliases.append(name_ru)
                collected["aliases"] = aliases

    await state.update_data(collected_data=collected)
    return await _finish_registration(message, state, collected, ctype, cls, raw_text)


# Maps (admin_chat_id, bot_message_id) -> (contractor_telegram_id, contractor_id)
# so admin can reply to a notification and the reply gets forwarded.
_admin_reply_map: dict[tuple[int, int], tuple[str, str]] = {}

async def handle_contractor_text(message: types.Message, state: FSMContext) -> str | None:
    """Catch-all: lookup contractor by telegram or name/alias.
    Returns 'register' or None.
    """
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    contractors = await get_contractors()
    telegram_id = message.from_user.id

    # Admins use commands, not free text
    if is_admin(telegram_id):
        await message.answer(replies.menu.admin)
        await state.clear()
        return None

    # Already bound? Show linked menu
    contractor = find_contractor_by_telegram_id(telegram_id, contractors)
    if contractor:
        await message.answer(
            replies.menu.prompt,
            reply_markup=_linked_menu_markup(contractor),
        )
        await state.clear()
        return None

    query = message.text.strip()

    # Fuzzy match → show buttons
    matches = fuzzy_find(query, contractors, threshold=0.8)
    if matches:
        await state.set_data({"alias": query})
        buttons = [
            [InlineKeyboardButton(
                text=_dup_button_label(c),
                callback_data=f"dup:{c.id}",
            )]
            for c, _ in matches[:5]
        ]
        buttons.append([InlineKeyboardButton(
            text=replies.lookup.new_contractor_btn,
            callback_data="dup:new",
        )])
        await message.answer(
            replies.lookup.fuzzy_match,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
        return None

    # No match → start registration
    await state.update_data(alias=query)
    return "register"


async def handle_non_document(message: types.Message, state: FSMContext) -> None:
    """Catch photos/stickers/etc — remind user to send text or PDF as appropriate."""
    current = await state.get_state()
    if current is not None:
        await message.answer(replies.generic.text_expected)
        return
    contractors = await get_contractors()
    contractor = find_contractor_by_telegram_id(message.from_user.id, contractors)
    if isinstance(contractor, GlobalContractor):
        await message.answer(replies.document.pdf_reminder)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Document upload callback
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def handle_document(message: types.Message, state: FSMContext) -> None:
    """Handle document uploads: forward contractor docs to admins.

    For Global contractors, also upload the signed proforma to Google Drive.
    """
    if is_admin(message.from_user.id):
        return

    contractors = await get_contractors()
    contractor = find_contractor_by_telegram_id(message.from_user.id, contractors)
    sender_info = contractor.display_name if contractor else f"TG#{message.from_user.id}"

    drive_link = None
    if isinstance(contractor, GlobalContractor) and message.document:
        mime = message.document.mime_type or ""
        if not mime.endswith("/pdf"):
            await message.answer(replies.document.pdf_required)
            return
        try:
            file = await bot.get_file(message.document.file_id)
            file_bytes = await bot.download_file(file.file_path)
            content = file_bytes.read()
            filename = message.document.file_name or f"{contractor.display_name}+Signed.pdf"
            month = prev_month()
            drive_link = await asyncio.to_thread(
                upload_invoice_pdf, contractor, month, filename, content,
            )
            await asyncio.to_thread(
                update_invoice_status, contractor.id, month, InvoiceStatus.SIGNED,
            )
        except Exception as e:
            logger.error("Failed to upload signed doc to Drive: %s", e)

    await message.answer(replies.document.received)
    for admin_id in ADMIN_TELEGRAM_IDS:
        if admin_id != message.from_user.id:
            try:
                caption = replies.document.forwarded_to_admin.format(name=sender_info)
                if drive_link:
                    caption += replies.document.forwarded_drive.format(link=drive_link)
                await bot.send_message(admin_id, caption)
                await bot.forward_message(admin_id, message.chat.id, message.message_id)
            except Exception:
                pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Admin command callbacks
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def cmd_generate(message: types.Message, state: FSMContext) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(replies.admin.generate_usage)
        return

    raw = args[1].strip()
    debug = raw.lower().startswith("debug ")
    query = raw[6:].strip() if debug else raw

    contractor = await _find_contractor_or_suggest(query, message)
    if not contractor:
        return

    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    month = prev_month()

    budget_amounts = await asyncio.to_thread(read_budget_amounts, month)
    articles = await asyncio.to_thread(fetch_articles, contractor, month)

    name_lower = contractor.display_name.lower().strip()
    budget_entry = budget_amounts.get(name_lower)
    if not budget_entry:
        await message.answer(
            replies.admin.not_in_budget.format(name=contractor.display_name, month=month)
        )
        return

    eur, rub, _note = budget_entry
    amount_int = eur if contractor.currency == Currency.EUR else rub
    if not amount_int:
        await message.answer(
            replies.admin.zero_amount.format(name=contractor.display_name, month=month)
        )
        return

    await message.answer(replies.invoice.generating_for.format(name=contractor.display_name))

    try:
        result = await asyncio.to_thread(
            create_and_save_invoice, contractor, month,
            Decimal(str(amount_int)), articles, debug=debug,
        )
    except Exception as e:
        await message.answer(replies.invoice.generation_error.format(error=e))
        logger.exception("Generate failed for %s", contractor.display_name)
        return

    tg_info = f"tg: {contractor.telegram}" if contractor.telegram else "tg id not found"
    filename = f"{contractor.display_name}+Unsigned.pdf"
    doc = BufferedInputFile(result.pdf_bytes, filename=filename)

    if debug:
        await message.answer_document(
            doc, caption=f"[DEBUG] {contractor.display_name} ({tg_info})",
        )
    elif isinstance(contractor, GlobalContractor):
        await message.answer_document(doc, caption=replies.admin.generate_caption.format(name=contractor.display_name))
        await message.answer(replies.admin.proforma_ready)
    else:
        caption = replies.invoice.legium_admin_caption.format(
            name=contractor.display_name, type=contractor.type.value,
            month=month, amount=amount_int,
        )
        sent = await message.answer_document(doc, caption=caption)
        _admin_reply_map[(message.chat.id, sent.message_id)] = (contractor.telegram, contractor.id)


async def handle_admin_reply(message: types.Message, state: FSMContext) -> None:
    """Forward admin's reply (Legium link) to the contractor and mark invoice as SENT."""
    reply = message.reply_to_message
    if not reply:
        return
    key = (message.chat.id, reply.message_id)
    entry = _admin_reply_map.get(key)
    if not entry:
        return
    contractor_tg, contractor_id = entry
    try:
        url = message.text.strip()
        month = prev_month()
        if contractor_tg:
            caption = replies.invoice.legium_link.format(url=url)
            contractors = await get_contractors()
            contractor = find_contractor_by_id(contractor_id, contractors)
            prepared = await asyncio.to_thread(prepare_existing_invoice, contractor, month) if contractor else None
            if prepared:
                filename = f"{contractor.display_name}+Unsigned.pdf"
                doc = BufferedInputFile(prepared.pdf_bytes, filename=filename)
                await bot.send_document(int(contractor_tg), doc, caption=caption)
            else:
                await bot.send_message(int(contractor_tg), caption)
            await asyncio.to_thread(
                update_legium_link, contractor_id, month, url,
            )
            await message.answer(replies.invoice.legium_sent)
        else:
            await asyncio.to_thread(
                update_legium_link, contractor_id, month, url, mark_sent=False,
            )
            await message.answer(replies.invoice.legium_saved)
        del _admin_reply_map[key]
    except Exception as e:
        await message.answer(replies.invoice.legium_send_error.format(error=e))


async def cmd_chatid(message: types.Message, state: FSMContext) -> None:
    await message.answer(f"Chat ID: `{message.chat.id}`", parse_mode="Markdown")


async def cmd_health(message: types.Message, state: FSMContext) -> None:
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    results = await asyncio.to_thread(run_healthchecks)
    await message.answer(format_healthcheck_results(results))


def _answer_tech_question(question: str, verbose: bool, expert: bool) -> str:
    gemini = GeminiGateway()

    needs_code = False
    try:
        prompt, model, _ = compose_request.tech_search_terms(question)
        result = gemini.call(prompt, model, task="TECH_SEARCH_TERMS")
        needs_code = bool(result.get("needs_code"))
    except Exception as e:
        logger.warning("Tech support triage failed: %s", e)

    if needs_code:
        return run_claude_code(question, verbose=verbose, expert=expert, mode="explore")

    prompt, model, _ = compose_request.tech_support_question(question, "", verbose)
    result = gemini.call(prompt, model)
    return result.get("answer", str(result))


async def cmd_support(message: types.Message, state: FSMContext) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer(replies.admin.support_usage)
        return

    verbose, expert, text = _parse_flags(args[1].strip())
    if not text:
        await message.answer(replies.admin.support_no_question)
        return

    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    try:
        answer = await asyncio.to_thread(_answer_tech_question, text, verbose, expert)
        if len(answer) > 4000:
            answer = answer[:4000] + "..."
        await _send_html(message, answer)
    except Exception as e:
        logger.exception("Support question failed")
        await message.answer(replies.admin.support_error)


async def cmd_code(message: types.Message, state: FSMContext) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer(replies.admin.code_usage)
        return

    verbose, expert, text = _parse_flags(args[1].strip())
    if not text:
        await message.answer(replies.admin.code_no_query)
        return

    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    try:
        answer = await asyncio.to_thread(run_claude_code, text, verbose, expert, mode="changes")
        # Save to DB and build rating keyboard
        reply_markup = None
        try:
            task_id = await asyncio.to_thread(
                _db.create_code_task,
                requested_by=str(message.from_user.id),
                input_text=text,
                output_text=answer,
                verbose=verbose,
            )
            reply_markup = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=str(i), callback_data=f"code_rate:{task_id}:{i}")
                for i in range(1, 6)
            ]])
        except Exception:
            logger.exception("Failed to save code task to DB")
        await _send_html(message, answer, reply_markup=reply_markup)
    except Exception as e:
        logger.exception("Claude Code execution failed")
        await message.answer(replies.admin.code_error)


_ROLE_LABELS = {
    RoleCode.AUTHOR: "автор",
    RoleCode.REDAKTOR: "редактор",
    RoleCode.KORREKTOR: "корректор",
}

async def cmd_articles(message: types.Message, state: FSMContext) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer(replies.admin.articles_usage)
        return

    rest = args[1].strip()
    # If last word looks like YYYY-MM, treat it as month
    parts = rest.rsplit(None, 1)
    if len(parts) == 2 and len(parts[1]) >= 6 and parts[1][:4].isdigit() and "-" in parts[1]:
        raw_name = parts[0]
        month = parts[1]
    else:
        raw_name = rest
        month = prev_month()

    contractor = await _find_contractor_or_suggest(raw_name, message)
    if not contractor:
        return

    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    articles = await asyncio.to_thread(fetch_articles, contractor, month)

    if not articles:
        await message.answer(replies.invoice.no_articles.format(name=contractor.display_name, month=month))
        return

    role_label = _ROLE_LABELS.get(contractor.role_code, contractor.role_code.value)
    ids_list = "\n".join(f"  - {a.article_id}" for a in articles)
    text = (
        f"{contractor.display_name} ({role_label})\n"
        f"Месяц: {month}\n"
        f"Статей: {len(articles)}\n\n"
        f"{ids_list}"
    )
    await message.answer(text)


async def cmd_lookup(message: types.Message, state: FSMContext) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(replies.admin.lookup_usage)
        return

    raw_name = args[1].strip()

    contractor = await _find_contractor_or_suggest(raw_name, message)
    if not contractor:
        return

    type_label = contractor.type.value
    role_label = _ROLE_LABELS.get(contractor.role_code, contractor.role_code.value)
    tg_status = "привязан" if contractor.telegram else "не привязан"

    has_bank = bool(contractor.bank_name and contractor.bank_account)
    bank_status = "заполнены" if has_bank else "не заполнены"

    lines = [
        f"{contractor.display_name}",
        f"Тип: {type_label}",
        f"Роль: {role_label}",
    ]
    if contractor.mags:
        lines.append(f"Издания: {contractor.mags}")
    if contractor.email:
        lines.append(f"Email: {contractor.email}")
    lines.append(f"Telegram: {tg_status}")
    lines.append(f"Номер счёта: {contractor.invoice_number}")
    lines.append(f"Банковские данные: {bank_status}")

    await message.answer("\n".join(lines))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GROUP CHAT HANDLER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_GROUP_COMMAND_HANDLERS: dict[str, Callable] = {
    "health": cmd_health,
    "support": cmd_support,
    "articles": cmd_articles,
    "lookup": cmd_lookup,
}

_COMMAND_DESCRIPTIONS: dict[str, str] = {
    "health": "Проверка доступности сайтов и подов",
    "support": "Любой вопрос о продукте, сайте, функциях, настройках, подписке или техподдержке",
    "articles": "Статьи контрагента за месяц",
    "lookup": "Информация о контрагенте",
}

# All commands available for admin /nl classification
_ADMIN_NL_DESCRIPTIONS: dict[str, str] = {
    **_COMMAND_DESCRIPTIONS,
    "generate": "Сгенерировать документ для контрагента",
    "generate_invoices": "Сгенерировать счета для всех контрагентов",
    "send_global_invoices": "Отправить глобальные счета контрагентам в Telegram",
    "send_legium_links": "Отправить ссылки на Легиум контрагентам в Telegram",
    "orphan_contractors": "Показать несовпадения между бюджетом и контрагентами",
    "budget": "Расчёт бюджета",
    "code": "Запустить Claude Code для внесения изменений в код",
}


async def cmd_nl(message: types.Message, state: FSMContext) -> None:
    """Natural language command classification for admin DM."""
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer("Использование: /nl <текст команды на естественном языке>")
        return

    text = args[1].strip()

    try:
        classifier = CommandClassifier(GeminiGateway())
        result = await asyncio.to_thread(
            classifier.classify, text, _ADMIN_NL_DESCRIPTIONS,
        )
    except Exception:
        logger.exception("NL classification failed")
        await message.answer("Не удалось классифицировать команду.")
        return

    if not result.classified:
        reply = result.reply or "Не удалось определить команду."
        await _send_html(message, reply)
        return

    cmd = result.classified.command
    cmd_args = result.classified.args or text

    # Build the handler map lazily (all cmd_* functions are defined by now)
    handlers: dict[str, Callable] = {
        **_GROUP_COMMAND_HANDLERS,
        "generate": cmd_generate,
        "generate_invoices": cmd_generate_invoices,
        "send_global_invoices": cmd_send_global_invoices,
        "send_legium_links": cmd_send_legium_links,
        "orphan_contractors": cmd_orphan_contractors,
        "budget": cmd_budget,
        "code": cmd_code,
    }

    handler = handlers.get(cmd)
    if not handler:
        await message.answer(f"Команда {cmd} не найдена.")
        return

    # Temporarily rewrite .text (Message is a frozen Pydantic model)
    original_text = message.text
    object.__setattr__(message, "text", f"/{cmd} {cmd_args}" if cmd_args else f"/{cmd}")
    try:
        await handler(message, state)
    finally:
        object.__setattr__(message, "text", original_text)


def _extract_bot_mention(text: str, bot_username: str) -> str | None:
    prefix = f"@{bot_username}"
    if text.startswith(prefix + " ") or text.startswith(prefix + "\n"):
        return text[len(prefix):].strip()
    return None


async def _dispatch_group_command(
    command: str, args_text: str, message: types.Message, state: FSMContext,
) -> None:
    if command == "menu":
        await message.answer(replies.menu.group)
        return
    handler = _GROUP_COMMAND_HANDLERS.get(command)
    if not handler:
        return
    original_text = message.text
    new_text = f"/{command} {args_text}" if args_text else f"/{command}"
    object.__setattr__(message, "text", new_text)
    try:
        await handler(message, state)
    finally:
        object.__setattr__(message, "text", original_text)


async def handle_group_message(
    message: types.Message, state: FSMContext, group_config: GroupChatConfig,
) -> None:
    text = message.text or ""

    # Explicit command (e.g. /health, /support@bot_username)
    if text.startswith("/"):
        raw_cmd = text.split()[0].lstrip("/")
        # Strip @bot_username suffix from command
        if "@" in raw_cmd:
            raw_cmd = raw_cmd.split("@", 1)[0]
        if raw_cmd not in group_config.allowed_commands:
            return
        args = text.split(maxsplit=1)
        args_text = args[1] if len(args) > 1 else ""
        await _dispatch_group_command(raw_cmd, args_text, message, state)
        return

    # Natural language: @mention or reply to bot message
    if not group_config.natural_language:
        return

    clean_text = _extract_bot_mention(text, BOT_USERNAME)
    is_reply_to_bot = (
        message.reply_to_message
        and message.reply_to_message.from_user
        and message.reply_to_message.from_user.is_bot
    )

    if clean_text is None and not is_reply_to_bot:
        return

    if clean_text is None:
        clean_text = text

    available_commands = {
        cmd: _COMMAND_DESCRIPTIONS[cmd]
        for cmd in group_config.allowed_commands
        if cmd in _COMMAND_DESCRIPTIONS
    }
    if not available_commands:
        return

    try:
        classifier = CommandClassifier(GeminiGateway())
        result = await asyncio.to_thread(
            classifier.classify, clean_text, available_commands,
        )
    except Exception:
        logger.exception("Command classification failed in group chat")
        return

    if not result.classified:
        if result.reply:
            await _send_html(message, result.reply)
        return

    await _dispatch_group_command(
        result.classified.command, result.classified.args or clean_text, message, state,
    )


async def cmd_budget(message: types.Message, state: FSMContext) -> None:
    """Generate the budget payments sheet."""
    args = message.text.split(maxsplit=1)
    month = args[1].strip() if len(args) > 1 else prev_month()

    await message.answer(replies.admin.budget_generating.format(month=month))
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    try:
        uc = ComputeBudget()
        url = await asyncio.to_thread(uc.execute, month)
        await message.answer(replies.admin.budget_done.format(url=url))
    except Exception as e:
        logger.exception("Budget generation failed")
        await message.answer(replies.admin.budget_error.format(error=e))


async def cmd_generate_invoices(message: types.Message, state: FSMContext) -> None:
    """Batch-generate invoices for all contractors."""
    debug = "debug" in message.text.lower().split()

    month = prev_month()
    status_msg = await message.answer(replies.admin.batch_generating.format(month=month))
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    contractors = await get_contractors()

    try:
        batch_result = await asyncio.to_thread(
            GenerateBatchInvoices().execute, contractors, month, debug,
        )
    except ValueError as e:
        await status_msg.edit_text(str(e))
        return

    if not batch_result.total:
        await status_msg.edit_text(replies.admin.batch_no_new.format(month=month))
        return

    # Summary message
    prefix = "[DEBUG] " if debug else ""
    counts = batch_result.counts
    parts = [replies.admin.batch_done.format(prefix=prefix, month=month)]
    generated = counts["global"] + counts["samozanyaty"] + counts["ip"]
    if generated:
        parts.append(replies.admin.batch_counts.format(
            global_=counts["global"], samozanyaty=counts["samozanyaty"], ip=counts["ip"],
        ))
    else:
        parts.append(replies.admin.batch_no_generated)
    if batch_result.errors:
        parts.append(replies.admin.batch_errors.format(
            errors="\n".join(f"  - {e}" for e in batch_result.errors),
        ))
    await message.answer("\n\n".join(parts))

    # Send PDFs to admin
    for pdf_bytes, contractor, invoice in batch_result.generated:
        tg_info = f"tg: {contractor.telegram}" if contractor.telegram else "tg id not found"
        if debug:
            filename = f"{contractor.display_name}+Unsigned.pdf"
            doc = BufferedInputFile(pdf_bytes, filename=filename)
            await message.answer_document(
                doc, caption=f"[DEBUG] {contractor.display_name} ({tg_info})",
            )
        elif contractor.currency == Currency.RUB:
            filename = f"СчетОферта_{contractor.display_name}_{month}.pdf"
            doc = BufferedInputFile(pdf_bytes, filename=filename)
            caption = replies.invoice.legium_admin_caption.format(
                name=contractor.display_name, type=contractor.type.value,
                month=month, amount=invoice.amount,
            )
            try:
                sent = await message.answer_document(doc, caption=caption)
                _admin_reply_map[(message.chat.id, sent.message_id)] = (contractor.telegram, contractor.id)
            except Exception:
                pass


async def cmd_send_global_invoices(message: types.Message, state: FSMContext) -> None:
    """Send generated global (EUR) invoice PDFs to contractors via Telegram."""
    debug = "debug" in message.text.lower().split()

    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    month = prev_month()
    invoices = await asyncio.to_thread(load_invoices, month)
    draft_global = [inv for inv in invoices if inv.status == InvoiceStatus.DRAFT and inv.currency == Currency.EUR]

    if not draft_global:
        await message.answer(replies.admin.no_draft_global.format(month=month))
        return

    contractors = await get_contractors()
    sent_count = 0
    errors: list[str] = []

    for inv in draft_global:
        contractor = find_contractor_by_id(inv.contractor_id, contractors)
        if not contractor:
            errors.append(f"{inv.contractor_id}: контрагент не найден")
            continue

        if not inv.doc_id:
            errors.append(f"{contractor.display_name}: нет doc_id для экспорта PDF")
            continue

        try:
            pdf_bytes = await asyncio.to_thread(export_pdf, inv.doc_id)
        except Exception as e:
            errors.append(f"{contractor.display_name}: ошибка экспорта PDF ({e})")
            continue

        filename = f"{contractor.display_name}+Unsigned.pdf"
        doc = BufferedInputFile(pdf_bytes, filename=filename)

        if debug:
            tg_info = f"tg: {contractor.telegram}" if contractor.telegram else "tg id not found"
            await message.answer_document(
                doc, caption=f"[DEBUG] {contractor.display_name} ({tg_info})",
            )
        else:
            if not contractor.telegram:
                errors.append(f"{contractor.display_name}: не привязан к Telegram")
                continue
            try:
                await bot.send_document(
                    int(contractor.telegram),
                    doc,
                    caption=replies.invoice.proforma_caption,
                )
            except Exception as e:
                errors.append(f"{contractor.display_name}: ошибка отправки ({e})")
                continue

        await asyncio.to_thread(
            update_invoice_status, inv.contractor_id, month, InvoiceStatus.SENT,
        )
        sent_count += 1

    prefix = "[DEBUG] " if debug else ""
    parts = [replies.admin.send_global_done.format(prefix=prefix, count=sent_count, month=month)]
    if errors:
        parts.append(replies.admin.batch_errors.format(
            errors="\n".join(f"  - {e}" for e in errors),
        ))
    await message.answer("\n\n".join(parts))


async def cmd_send_legium_links(message: types.Message, state: FSMContext) -> None:
    """Batch-send legium links to contractors whose invoices have a link but are still DRAFT."""
    debug = "debug" in message.text.lower().split()

    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    month = prev_month()
    invoices = await asyncio.to_thread(load_invoices, month)
    pending = [inv for inv in invoices if inv.legium_link and inv.status == InvoiceStatus.DRAFT]

    if not pending:
        await message.answer(replies.admin.no_legium_pending.format(month=month))
        return

    contractors = await get_contractors()
    sent_count = 0
    errors: list[str] = []

    for inv in pending:
        contractor = find_contractor_by_id(inv.contractor_id, contractors)
        if not contractor:
            errors.append(f"{inv.contractor_id}: контрагент не найден")
            continue

        if debug:
            tg_info = f"tg: {contractor.telegram}" if contractor.telegram else "tg id not found"
            await message.answer(
                f"[DEBUG] {contractor.display_name} ({tg_info})\n{inv.legium_link}",
            )
        else:
            if not contractor.telegram:
                errors.append(f"{contractor.display_name}: не привязан к Telegram")
                continue
            try:
                caption = replies.invoice.legium_link.format(url=inv.legium_link)
                prepared = await asyncio.to_thread(prepare_existing_invoice, contractor, month)
                if prepared:
                    filename = f"{contractor.display_name}+Unsigned.pdf"
                    doc = BufferedInputFile(prepared.pdf_bytes, filename=filename)
                    await bot.send_document(int(contractor.telegram), doc, caption=caption)
                else:
                    await bot.send_message(int(contractor.telegram), caption)
            except Exception as e:
                errors.append(f"{contractor.display_name}: ошибка отправки ({e})")
                continue

        await asyncio.to_thread(
            update_invoice_status, inv.contractor_id, month, InvoiceStatus.SENT,
        )
        sent_count += 1

    prefix = "[DEBUG] " if debug else ""
    parts = [replies.admin.send_legium_done.format(prefix=prefix, count=sent_count, month=month)]
    if errors:
        parts.append(replies.admin.batch_errors.format(
            errors="\n".join(f"  - {e}" for e in errors),
        ))
    await message.answer("\n\n".join(parts))


async def cmd_orphan_contractors(message: types.Message, state: FSMContext) -> None:
    """Show budget entries that don't match any contractor."""
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    month = prev_month()
    contractors = await get_contractors()
    budget_amounts = await asyncio.to_thread(read_budget_amounts, month)

    contractor_names = {c.display_name.lower().strip() for c in contractors}
    orphans = sorted(n for n in budget_amounts if n not in contractor_names)

    if not orphans:
        await message.answer(replies.admin.orphans_none.format(month=month))
        return

    lines = "\n".join(f"  - {n}" for n in orphans)
    await message.answer(replies.admin.orphans_found.format(month=month, count=len(orphans), lines=lines))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Private helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def _start_invoice_flow(
    message: types.Message, state: FSMContext, contractor: Contractor,
) -> str | None:
    """Fetch budget + articles and prompt for amount. Returns "invoice" or None."""
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    month = prev_month()
    budget_amounts = await asyncio.to_thread(read_budget_amounts, month)
    articles = await asyncio.to_thread(fetch_articles, contractor, month)
    num_articles = len(articles)

    default_amount_int, explanation = resolve_amount(
        budget_amounts, contractor, num_articles,
    )
    if not default_amount_int:
        return None

    article_ids = [a.article_id for a in articles]
    await state.update_data(
        invoice_contractor_id=contractor.id,
        invoice_month=month,
        invoice_article_ids=article_ids,
        invoice_default_amount=default_amount_int,
    )
    pub_word = plural_ru(num_articles, "публикация", "публикации", "публикаций") if num_articles else "0 публикаций"
    await message.answer(
        replies.invoice.amount_prompt.format(
            pub_word=pub_word, month=month, explanation=explanation,
        )
    )
    return "invoice"


async def _notify_admins_rub_invoice(
    pdf_bytes: bytes, filename: str, contractor: Contractor,
    month: str, amount,
) -> None:
    for admin_id in ADMIN_TELEGRAM_IDS:
        try:
            admin_doc = BufferedInputFile(pdf_bytes, filename=filename)
            caption = replies.invoice.legium_admin_caption.format(
                name=contractor.display_name, type=contractor.type.value,
                month=month, amount=amount,
            )
            sent = await bot.send_document(admin_id, admin_doc, caption=caption)
            _admin_reply_map[(admin_id, sent.message_id)] = (contractor.telegram, contractor.id)
        except Exception:
            pass


async def _deliver_existing_invoice(message: types.Message, contractor: Contractor) -> bool:
    """Check for a pre-generated invoice and deliver it to the contractor.

    Returns True if an invoice was found and handled, False otherwise.
    """
    month = prev_month()
    prepared = await asyncio.to_thread(prepare_existing_invoice, contractor, month)
    if not prepared:
        return False

    inv = prepared.invoice
    filename = f"{contractor.display_name}+Unsigned.pdf"
    doc = BufferedInputFile(prepared.pdf_bytes, filename=filename)

    if contractor.currency == Currency.EUR:
        if inv.status == InvoiceStatus.DRAFT:
            await bot.send_document(
                message.chat.id, doc,
                caption=replies.invoice.proforma_caption,
            )
            await asyncio.to_thread(
                update_invoice_status, inv.contractor_id, month, InvoiceStatus.SENT,
            )
        else:
            await message.answer(replies.invoice.proforma_already_sent)
    else:
        # RUB contractor
        if inv.legium_link:
            await bot.send_document(
                message.chat.id, doc,
                caption=replies.invoice.legium_link.format(url=inv.legium_link),
            )
            if inv.status == InvoiceStatus.DRAFT:
                await asyncio.to_thread(
                    update_invoice_status, inv.contractor_id, month, InvoiceStatus.SENT,
                )
        elif inv.status == InvoiceStatus.DRAFT:
            await bot.send_document(
                message.chat.id, doc,
                caption=replies.invoice.rub_invoice_caption,
            )
            await _notify_admins_rub_invoice(prepared.pdf_bytes, filename, contractor, month, inv.amount)
        else:
            await message.answer(replies.invoice.legium_already_sent)

    return True


async def handle_duplicate_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle inline button press for duplicate contractor selection."""
    data_str = callback.data
    await callback.answer()

    if data_str == "dup:new":
        try:
            await callback.message.delete()
        except TelegramBadRequest:
            pass
        await state.set_state("ContractorStates:waiting_type")
        await callback.message.answer(replies.registration.type_prompt)
        return

    contractor_id = data_str.removeprefix("dup:")
    contractors = await get_contractors()
    contractor = find_contractor_by_id(contractor_id, contractors)
    if not contractor:
        await callback.message.answer(replies.lookup.not_found)
        return

    await _safe_edit_text(
        callback.message,
        replies.lookup.selected.format(name=contractor.display_name),
        reply_markup=None,
    )
    await bot.send_chat_action(callback.message.chat.id, ChatAction.TYPING)

    telegram_id = callback.from_user.id

    # Already bound to a different Telegram account?
    if contractor.telegram and contractor.telegram != str(telegram_id):
        await callback.message.answer(
            replies.verification.already_bound.format(name=contractor.display_name)
        )
        return

    # Enter verification: ask for secret code
    await state.update_data(pending_contractor_id=contractor.id, verification_attempts=0)
    await state.set_state("ContractorStates:waiting_verification")
    await callback.message.answer(
        replies.verification.code_prompt.format(name=contractor.display_name)
    )


async def handle_linked_menu_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle inline button press from the linked user menu."""
    await callback.answer()
    contractors = await get_contractors()
    contractor = find_contractor_by_telegram_id(callback.from_user.id, contractors)
    if not contractor:
        await callback.message.answer(replies.lookup.not_found)
        return

    action = callback.data.removeprefix("menu:")

    if action == "contract":
        await _deliver_or_start_invoice(callback.message, state, contractor)
    elif action == "update":
        await state.set_state("ContractorStates:waiting_update_data")
        await callback.message.answer(replies.linked_menu.update_prompt)
    elif action == "editor":
        await _show_editor_sources(callback, contractor)


def _editor_sources_content(rules) -> tuple[str, InlineKeyboardMarkup]:
    """Build text and keyboard for the editor sources list."""
    rows: list[list[InlineKeyboardButton]] = []
    if rules:
        text = replies.editor_sources.header + "\n"
        for r in rules:
            text += f"\n  - {r.source_name}"
            rows.append([
                InlineKeyboardButton(
                    text=f"{replies.editor_sources.btn_remove} {r.source_name}",
                    callback_data=f"esrc:rm:{r.source_name}",
                ),
            ])
    else:
        text = replies.editor_sources.empty
    rows.append([InlineKeyboardButton(text=replies.editor_sources.btn_add, callback_data="esrc:add")])
    rows.append([InlineKeyboardButton(text=replies.editor_sources.btn_back, callback_data="esrc:back")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


async def _show_editor_sources(callback: CallbackQuery, contractor: Contractor) -> None:
    """Render the editor sources list with inline buttons."""
    rules = await asyncio.to_thread(find_redirect_rules_by_target, contractor.id)
    text, markup = _editor_sources_content(rules)
    await _safe_edit_text(callback.message, text, reply_markup=markup)


async def handle_editor_source_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle editor source management callbacks (esrc: prefix)."""
    contractors = await get_contractors()
    contractor = find_contractor_by_telegram_id(callback.from_user.id, contractors)
    if not contractor:
        await callback.answer()
        await callback.message.answer(replies.lookup.not_found)
        return

    data = callback.data.removeprefix("esrc:")

    if data.startswith("rm:"):
        source_name = data.removeprefix("rm:")
        removed = await asyncio.to_thread(remove_redirect_rule, source_name, contractor.id)
        if removed:
            month = prev_month()
            await asyncio.to_thread(delete_invoice, contractor.id, month)
            await asyncio.to_thread(unredirect_in_budget, source_name, contractor, month)
            await callback.answer(replies.editor_sources.removed.format(name=source_name))
        else:
            await callback.answer()
        await _show_editor_sources(callback, contractor)

    elif data == "add":
        await callback.answer()
        await state.set_state("ContractorStates:waiting_editor_source_name")
        try:
            await callback.message.edit_text(replies.editor_sources.add_prompt, reply_markup=None)
        except TelegramBadRequest:
            await callback.message.answer(replies.editor_sources.add_prompt)

    elif data == "back":
        await callback.answer()
        await _safe_edit_text(
            callback.message,
            replies.menu.prompt,
            reply_markup=_linked_menu_markup(contractor),
        )


async def handle_editor_source_name(message: types.Message, state: FSMContext) -> str | None:
    """Handle text input for adding a new editor source. Returns 'done' or None."""
    if message.text and message.text.strip().lower() == "отмена":
        await state.clear()
        await message.answer(replies.editor_sources.add_cancelled)
        return "done"

    contractors = await get_contractors()
    contractor = find_contractor_by_telegram_id(message.from_user.id, contractors)
    if not contractor:
        await message.answer(replies.lookup.not_found)
        await state.clear()
        return "done"

    source_name = message.text.strip()
    month = prev_month()
    await asyncio.to_thread(add_redirect_rule, source_name, contractor.id)
    await asyncio.to_thread(delete_invoice, contractor.id, month)
    await asyncio.to_thread(redirect_in_budget, source_name, contractor, month)
    await message.answer(replies.editor_sources.added.format(name=source_name))

    # Show updated list as a new message (can't edit since user sent text)
    rules = await asyncio.to_thread(find_redirect_rules_by_target, contractor.id)
    text, markup = _editor_sources_content(rules)
    await message.answer(text, reply_markup=markup)
    return "done"


async def handle_update_data(message: types.Message, state: FSMContext) -> str | None:
    """Parse free-form update text and write changes to sheet. Returns 'done' or None."""
    if message.text and message.text.strip().lower() == "отмена":
        await state.clear()
        await message.answer(replies.linked_menu.update_cancelled)
        return "done"

    contractors = await get_contractors()
    contractor = find_contractor_by_telegram_id(message.from_user.id, contractors)
    if not contractor:
        await message.answer(replies.lookup.not_found)
        await state.clear()
        return "done"

    parsed = await _parse_with_llm(message.text.strip(), contractor.type)
    if "parse_error" in parsed:
        await message.answer(replies.registration.parse_error)
        return None

    parsed_updates = {k: v for k, v in parsed.items() if isinstance(v, str) and v.strip() and not k.startswith("_")}
    parsed_updates.pop("comment", None)

    if not parsed_updates:
        await message.answer(replies.linked_menu.no_changes)
        return None

    await asyncio.to_thread(update_contractor_fields, contractor.id, parsed_updates)
    await message.answer(replies.linked_menu.update_success)
    return "done"


async def handle_verification_code(message: types.Message, state: FSMContext) -> str | None:
    """Verify secret code for contractor binding. Returns 'verified' or None."""
    data = await state.get_data()
    contractor_id = data.get("pending_contractor_id")
    attempts = data.get("verification_attempts", 0)

    contractors = await get_contractors()
    contractor = find_contractor_by_id(contractor_id, contractors)
    if not contractor:
        await message.answer(replies.lookup.not_found)
        await state.clear()
        return None

    code = message.text.strip()
    if code.casefold() == contractor.secret_code.casefold():
        telegram_id = message.from_user.id
        await asyncio.to_thread(bind_telegram_id, contractor.id, telegram_id)
        contractor.telegram = str(telegram_id)
        await message.answer(
            replies.verification.success.format(name=contractor.display_name)
        )
        for admin_id in ADMIN_TELEGRAM_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    replies.notifications.contractor_linked.format(name=contractor.display_name),
                )
            except Exception:
                pass
        await message.answer(
            replies.menu.prompt,
            reply_markup=_linked_menu_markup(contractor),
        )
        await state.clear()
        return "verified"

    attempts += 1
    if attempts >= 3:
        await message.answer(replies.verification.too_many_attempts)
        await state.clear()
        return None

    remaining = 3 - attempts
    await state.update_data(verification_attempts=attempts)
    await message.answer(replies.verification.wrong_code.format(remaining=remaining))
    return None


async def _finish_registration(
    message: types.Message, state: FSMContext,
    collected: dict, ctype: ContractorType, cls: type, raw_text: str,
) -> str | None:
    """Final step: save contractor and confirm registration."""
    all_labels = cls.all_field_labels()
    summary = "\n".join(
        f"  {label}: {collected.get(field, '')}"
        for field, label in all_labels.items()
        if collected.get(field)
    )
    aliases = collected.get("aliases", [])
    if aliases:
        summary += f"\n  псевдонимы: {', '.join(aliases)}"

    telegram_id = str(message.from_user.id)
    contractor, secret_code = await _save_new_contractor(collected, ctype, telegram_id)
    await _forward_to_admins(raw_text, ctype, collected)

    validation_id = collected.get("_validation_id")
    if validation_id:
        try:
            await asyncio.to_thread(_db.finalize_payment_validation, validation_id)
        except Exception:
            logger.warning("Failed to finalize payment validation %s", validation_id, exc_info=True)

    text = replies.registration.complete_summary.format(summary=summary)
    if secret_code:
        text += replies.registration.complete_secret.format(code=secret_code)
    await message.answer(text)

    if not contractor:
        return "complete"

    # Check budget sheet / articles → start invoice flow
    result = await _start_invoice_flow(message, state, contractor)
    if not result:
        await message.answer(replies.registration.no_articles.format(month=prev_month()))
        return "complete"
    return result


async def handle_amount_input(message: types.Message, state: FSMContext) -> str | None:
    """Handle amount input from new contractors. Returns 'done' or None."""
    data = await state.get_data()
    contractor_id = data.get("invoice_contractor_id")
    month = data.get("invoice_month")
    default_amount = data.get("invoice_default_amount", 0)

    contractors = await get_contractors()
    contractor = find_contractor_by_id(contractor_id, contractors)
    if not contractor:
        await message.answer(replies.lookup.not_found)
        return "done"

    text = message.text.strip()
    if text.lower() in ("ок", "ok"):
        amount = Decimal(str(default_amount))
    else:
        cleaned = re.sub(r"[^\d.]", "", text)
        if not cleaned:
            await message.answer(replies.invoice.amount_invalid)
            return None
        try:
            amount = Decimal(cleaned)
        except Exception:
            await message.answer(replies.invoice.amount_parse_error)
            return None

    await message.answer(replies.invoice.generating)

    articles = await asyncio.to_thread(fetch_articles, contractor, month)

    try:
        result = await asyncio.to_thread(
            create_and_save_invoice, contractor, month, amount, articles,
        )
    except Exception as e:
        await message.answer(replies.invoice.generation_error.format(error=e))
        logger.exception("Generate failed for %s", contractor.display_name)
        return "done"

    invoice = result.invoice
    filename = f"{contractor.display_name}+Unsigned.pdf"
    doc = BufferedInputFile(result.pdf_bytes, filename=filename)

    if contractor.currency == Currency.EUR:
        await bot.send_document(
            message.chat.id, doc,
            caption=replies.invoice.proforma_caption,
        )
        await asyncio.to_thread(
            update_invoice_status, invoice.contractor_id, month, InvoiceStatus.SENT,
        )
    else:
        await bot.send_document(
            message.chat.id, doc,
            caption=replies.invoice.rub_invoice_caption,
        )
        await _notify_admins_rub_invoice(result.pdf_bytes, filename, contractor, month, invoice.amount)

    return "done"


async def _save_new_contractor(
    collected: dict, ctype: ContractorType, telegram_id: str,
) -> tuple[Contractor | None, str]:
    """Create Contractor subclass from registration data and save to Google Sheet.

    Returns (contractor, secret_code).
    """
    try:
        contractors = await get_contractors()
        cid = next_contractor_id(contractors)
        cls = CONTRACTOR_CLASS_BY_TYPE[ctype]

        code = await asyncio.to_thread(pop_random_secret_code)

        kwargs = dict(
            id=cid,
            aliases=collected.get("aliases", []),
            email=collected.get("email", ""),
            bank_name=collected.get("bank_name", ""),
            bank_account=collected.get("bank_account", ""),
            telegram=telegram_id,
            secret_code=code,
        )
        for field in cls.FIELD_META:
            if field not in kwargs:
                kwargs[field] = collected.get(field, "")

        contractor = cls(**kwargs)
        await asyncio.to_thread(save_contractor, contractor)
        logger.info("Auto-saved new contractor %s (%s)", cid, contractor.display_name)
        return contractor, code
    except Exception as e:
        logger.error("Failed to auto-save contractor: %s", e)
        return None, ""


async def _forward_to_admins(raw_text: str, ctype: ContractorType, parsed: dict) -> None:
    """Forward registration data to all admin Telegram IDs."""
    for admin_id in ADMIN_TELEGRAM_IDS:
        try:
            msg = replies.notifications.new_registration.format(type=ctype.value, raw_text=raw_text)
            if parsed:
                formatted = "\n".join(f"  {k}: {v}" for k, v in parsed.items() if v and not k.startswith("_"))
                msg += replies.notifications.new_registration_parsed.format(formatted=formatted)
            await bot.send_message(admin_id, msg)
        except Exception:
            pass


async def _parse_with_llm(
    text: str, ctype: ContractorType,
    collected: dict | None = None, warnings: list[str] | None = None,
) -> dict:
    """Parse contractor data from free-form text using Gemini."""
    cls = CONTRACTOR_CLASS_BY_TYPE[ctype]
    fields = cls.field_names_csv()

    context = ""
    if collected:
        filled = {k: v for k, v in collected.items() if v and not k.startswith("_")}
        missing = [f for f in cls.FIELD_META if f not in filled]
        if filled:
            context += f"\nУже получено: {json.dumps(filled, ensure_ascii=False)}"
        if missing:
            context += f"\nЕщё не заполнены: {', '.join(missing)}"
        if warnings:
            context += (
                "\nСледующие поля имеют ошибки валидации, пользователь "
                "скорее всего исправляет их. Объедини новый ввод с уже "
                "собранными данными, чтобы получить исправленное значение:\n"
                + "\n".join(f"- {w}" for w in warnings)
            )

    result = await asyncio.to_thread(parse_contractor_data, text, fields, context)

    if "parse_error" not in result:
        try:
            vid = await asyncio.to_thread(
                _db.log_payment_validation,
                contractor_id="", contractor_type=ctype.value,
                input_text=text, parsed_json=json.dumps(result, ensure_ascii=False),
            )
            result["_validation_id"] = vid
        except Exception:
            logger.warning("Failed to log payment validation", exc_info=True)

    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  /upload_to_airtable — parse bank CSV and upload expenses
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def cmd_upload_to_airtable(message: types.Message, state: FSMContext) -> None:
    """Parse an attached bank statement CSV and upload expenses to Airtable."""
    text = message.text or message.caption or ""
    args = text.split(maxsplit=1)

    if not message.document:
        await message.answer(replies.admin.upload_usage)
        return

    if len(args) < 2:
        await message.answer(replies.admin.upload_usage)
        return

    try:
        rate = float(args[1].strip())
    except ValueError:
        await message.answer(replies.admin.upload_usage)
        return

    await message.answer(replies.admin.upload_processing.format(rate=rate))
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    file = await bot.get_file(message.document.file_id)
    file_bytes = await bot.download_file(file.file_path)

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            tmp.write(file_bytes.read())
            tmp_path = tmp.name

        uc = ParseBankStatement()
        expenses = await asyncio.to_thread(uc.execute, tmp_path, rate, True)

        review_count = sum(1 for e in expenses if e.comment == "NEEDS REVIEW")
        text = replies.admin.upload_done.format(count=len(expenses))
        if review_count:
            text += replies.admin.upload_needs_review.format(count=review_count)
        await message.answer(text)
    except Exception as e:
        logger.exception("Airtable upload failed")
        await message.answer(replies.admin.upload_error.format(error=e))
    finally:
        if tmp_path:
            os.unlink(tmp_path)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Inbox: background listener + callback handlers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_inbox = InboxService()


async def email_listener_task() -> None:
    """Background task: listen for new emails, classify, and send to admin."""
    if not ADMIN_TELEGRAM_IDS:
        logger.warning("No admin IDs configured, email listener disabled")
        return
    admin_id = ADMIN_TELEGRAM_IDS[0]
    logger.info("Email listener started for %s", EMAIL_ADDRESS)
    while True:
        try:
            has_new = await asyncio.to_thread(_inbox.idle_wait, 300)
            if not has_new:
                continue
            emails = await asyncio.to_thread(_inbox.fetch_unread)
            for em in emails:
                result = await asyncio.to_thread(_inbox.process, em)
                if not result:
                    continue
                if result.category == "tech_support":
                    await _send_support_draft(admin_id, result.draft)
                elif result.category == "editorial":
                    await _send_editorial(admin_id, result.editorial)
        except Exception as e:
            logger.exception("Email listener error: %s", e)
            await asyncio.sleep(30)


async def _send_support_draft(admin_id: int, draft: SupportDraft) -> None:
    em = draft.email
    body_preview = em.body[:500] + ("..." if len(em.body) > 500 else "")
    header = f"From: {em.from_addr}\n"
    if em.reply_to and em.reply_to != em.from_addr:
        header += f"Reply-To: {em.reply_to}\n"
    draft_header = replies.tech_support.draft_header if draft.can_answer else replies.tech_support.draft_header_uncertain
    text = (
        f"{header}"
        f"Subject: {em.subject}\n\n"
        f"{body_preview}\n\n"
        f"{draft_header}\n"
        f"{draft.draft_reply}"
    )
    buttons = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=replies.tech_support.btn_send, callback_data=f"support:send:{em.uid}"),
        InlineKeyboardButton(text=replies.tech_support.btn_skip, callback_data=f"support:skip:{em.uid}"),
    ]])
    await bot.send_message(admin_id, text, reply_markup=buttons)


async def _send_editorial(admin_id: int, item: EditorialItem) -> None:
    em = item.email
    body_preview = em.body[:500] + ("..." if len(em.body) > 500 else "")
    text = (
        f"Письмо в редакцию\n"
        f"From: {em.from_addr}\n"
        f"Subject: {em.subject}\n\n"
        f"{body_preview}"
    )
    if item.reply_to_sender:
        text += f"\n\n--- Автоответ ---\n{item.reply_to_sender}"
    buttons = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=replies.editorial.btn_forward, callback_data=f"editorial:fwd:{em.uid}"),
        InlineKeyboardButton(text=replies.editorial.btn_skip, callback_data=f"editorial:skip:{em.uid}"),
    ]])
    await bot.send_message(admin_id, text, reply_markup=buttons)


async def handle_support_callback(callback: CallbackQuery) -> None:
    """Handle send/skip button presses for tech support drafts."""
    await callback.answer()
    parts = callback.data.split(":")
    if len(parts) != 3:
        return
    _, action, uid = parts

    draft = _inbox.get_pending_support(uid)
    if not draft:
        await _safe_edit_text(callback.message, replies.tech_support.expired)
        return

    if action == "send":
        await asyncio.to_thread(_inbox.approve_support, uid)
        await _safe_edit_text(callback.message, replies.tech_support.reply_sent.format(addr=draft.email.reply_to or draft.email.from_addr))
    elif action == "skip":
        await asyncio.to_thread(_inbox.skip_support, uid)
        await _safe_edit_text(callback.message, replies.tech_support.skipped.format(from_addr=draft.email.from_addr))


async def handle_editorial_callback(callback: CallbackQuery) -> None:
    """Handle forward/skip button presses for editorial items."""
    await callback.answer()
    parts = callback.data.split(":")
    if len(parts) != 3:
        return
    _, action, uid = parts

    item = _inbox.get_pending_editorial(uid)
    if not item:
        await _safe_edit_text(callback.message, replies.editorial.expired)
        return

    if action == "fwd":
        await asyncio.to_thread(_inbox.approve_editorial, uid)
        await _safe_edit_text(callback.message, replies.editorial.forwarded.format(from_addr=item.email.from_addr, subject=item.email.subject))
    elif action == "skip":
        await asyncio.to_thread(_inbox.skip_editorial, uid)
        await _safe_edit_text(callback.message, replies.editorial.skipped.format(from_addr=item.email.from_addr))


async def handle_code_rate_callback(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    _, task_id, rating = parts
    try:
        await asyncio.to_thread(_db.rate_code_task, task_id, int(rating))
    except Exception:
        logger.exception("Failed to save code task rating")
    await callback.answer("Оценка сохранена!")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
