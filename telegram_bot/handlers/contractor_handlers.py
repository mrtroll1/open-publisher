"""Contractor registration, linking, and invoice flow handlers."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from decimal import Decimal

from aiogram import types
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery

from common.config import ADMIN_TELEGRAM_IDS
from common.models import (
    CONTRACTOR_CLASS_BY_TYPE,
    Contractor,
    ContractorType,
    Currency,
    GlobalContractor,
    InvoiceStatus,
    RoleCode,
)
from backend import (
    add_redirect_rule,
    bind_telegram_id,
    create_and_save_invoice,
    delete_invoice,
    fetch_articles,
    find_contractor_by_id,
    find_contractor_by_telegram_id,
    find_redirect_rules_by_target,
    fuzzy_find,
    next_contractor_id,
    parse_contractor_data,
    plural_ru,
    pop_random_secret_code,
    prepare_existing_invoice,
    read_budget_amounts,
    redirect_in_budget,
    remove_redirect_rule,
    resolve_amount,
    save_contractor,
    translate_name_to_russian,
    unredirect_in_budget,
    update_contractor_fields,
    update_invoice_status,
    upload_invoice_pdf,
    validate_contractor_fields,
)
from telegram_bot import replies
from telegram_bot.bot_helpers import bot, get_contractors, is_admin, prev_month
from telegram_bot.handler_utils import (
    _admin_reply_map,
    _db,
    _safe_edit_text,
)

logger = logging.getLogger(__name__)

__all__ = [
    "_linked_menu_markup",
    "handle_start",
    "handle_menu",
    "_deliver_or_start_invoice",
    "handle_sign_doc",
    "handle_update_payment_data",
    "handle_manage_redirects",
    "_dup_button_label",
    "handle_type_selection",
    "handle_data_input",
    "handle_contractor_text",
    "handle_non_document",
    "handle_document",
    "_start_invoice_flow",
    "_notify_admins_rub_invoice",
    "_deliver_existing_invoice",
    "handle_duplicate_callback",
    "handle_linked_menu_callback",
    "_editor_sources_content",
    "_show_editor_sources",
    "handle_editor_source_callback",
    "handle_editor_source_name",
    "handle_update_data",
    "handle_verification_code",
    "_finish_registration",
    "handle_amount_input",
    "_save_new_contractor",
    "_forward_to_admins",
    "_parse_with_llm",
]


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
