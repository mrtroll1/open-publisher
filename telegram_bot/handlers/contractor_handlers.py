"""Contractor registration, linking, and invoice flow handlers."""

from __future__ import annotations

import asyncio
import logging
import re
from decimal import Decimal

from aiogram import types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery

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
    find_contractor_by_telegram_id,
    find_redirect_rules_by_target,
    fuzzy_find,
    redirect_in_budget,
    remove_redirect_rule,
    unredirect_in_budget,
    update_contractor_fields,
    update_invoice_status,
    upload_invoice_pdf,
    validate_contractor_fields,
)
from backend.commands.contractor.create import (
    check_registration_complete,
    create_contractor,
)
from backend.commands.contractor.registration import (
    parse_registration_data,
    translate_contractor_name,
)
from backend.commands.invoice.service import (
    DeliveryAction,
    prepare_new_invoice_data,
    resolve_existing_invoice,
)
from telegram_bot import replies
from telegram_bot.bot_helpers import bot, get_admin_ids, get_contractors, is_admin, prev_month
from telegram_bot import backend_client
from telegram_bot.handler_utils import (
    _admin_reply_map,
    _safe_edit_text,
    _send,
    get_contractor_by_id,
    get_current_contractor,
    send_typing,
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
    contractor = await get_current_contractor(message.from_user.id)
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
    await send_typing(message.chat.id)
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
    contractor = await get_current_contractor(message.from_user.id)
    if not contractor:
        await message.answer(replies.start.contractor)
        return
    await _deliver_or_start_invoice(message, state, contractor)


async def handle_update_payment_data(message: types.Message, state: FSMContext) -> None:
    await state.clear()
    contractor = await get_current_contractor(message.from_user.id)
    if not contractor:
        await message.answer(replies.start.contractor)
        return
    await state.set_state("ContractorStates:waiting_update_data")
    await message.answer(replies.linked_menu.update_prompt)


async def handle_manage_redirects(message: types.Message, state: FSMContext) -> None:
    await state.clear()
    contractor = await get_current_contractor(message.from_user.id)
    if not contractor or contractor.role_code != RoleCode.REDAKTOR:
        await message.answer(replies.start.contractor)
        return
    await send_typing(message.chat.id)
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
    _, missing = check_registration_complete(collected, required)
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
        await _send(message, "\n\n".join(parts))
        return None

    # For Global contractors, translate name to Russian and add as alias
    if ctype == ContractorType.GLOBAL:
        name_en = collected.get("name_en", "")
        if name_en:
            name_ru = await asyncio.to_thread(translate_contractor_name, name_en)
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
    await send_typing(message.chat.id)
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
    contractor = await get_current_contractor(message.from_user.id)
    if isinstance(contractor, GlobalContractor):
        await message.answer(replies.document.pdf_reminder)


async def handle_document(message: types.Message, state: FSMContext) -> None:
    """Handle document uploads: forward contractor docs to admins.

    For Global contractors, also upload the signed proforma to Google Drive.
    """
    if is_admin(message.from_user.id):
        return

    contractor = await get_current_contractor(message.from_user.id)
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
    for admin_id in get_admin_ids():
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
    await send_typing(message.chat.id)
    month = prev_month()
    data = await asyncio.to_thread(prepare_new_invoice_data, contractor, month)
    if not data:
        return None

    await state.update_data(
        invoice_contractor_id=contractor.id,
        invoice_month=month,
        invoice_article_ids=data.article_ids,
        invoice_default_amount=data.default_amount,
    )
    await message.answer(
        replies.invoice.amount_prompt.format(
            pub_word=data.pub_word, month=month, explanation=data.explanation,
        )
    )
    return "invoice"


async def _notify_admins_rub_invoice(
    pdf_bytes: bytes, filename: str, contractor: Contractor,
    month: str, amount,
) -> None:
    for admin_id in get_admin_ids():
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
    result = await asyncio.to_thread(resolve_existing_invoice, contractor, month)
    if not result:
        return False

    inv = result.prepared.invoice
    filename = f"{contractor.display_name}+Unsigned.pdf"
    doc = BufferedInputFile(result.prepared.pdf_bytes, filename=filename)
    action = result.action

    if action == DeliveryAction.SEND_PROFORMA:
        await bot.send_document(message.chat.id, doc, caption=replies.invoice.proforma_caption)
        await asyncio.to_thread(update_invoice_status, inv.contractor_id, month, InvoiceStatus.SENT)
    elif action == DeliveryAction.PROFORMA_ALREADY_SENT:
        await message.answer(replies.invoice.proforma_already_sent)
    elif action == DeliveryAction.SEND_RUB_WITH_LEGIUM:
        await bot.send_document(
            message.chat.id, doc,
            caption=replies.invoice.legium_link.format(url=inv.legium_link),
        )
        if inv.status == InvoiceStatus.DRAFT:
            await asyncio.to_thread(update_invoice_status, inv.contractor_id, month, InvoiceStatus.SENT)
    elif action == DeliveryAction.SEND_RUB_DRAFT:
        await bot.send_document(message.chat.id, doc, caption=replies.invoice.rub_invoice_caption)
        await _notify_admins_rub_invoice(result.prepared.pdf_bytes, filename, contractor, month, inv.amount)
    elif action == DeliveryAction.RUB_ALREADY_SENT:
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
    contractor = await get_contractor_by_id(contractor_id)
    if not contractor:
        await callback.message.answer(replies.lookup.not_found)
        return

    await _safe_edit_text(
        callback.message,
        replies.lookup.selected.format(name=contractor.display_name),
        reply_markup=None,
    )
    await send_typing(callback.message.chat.id)

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
    contractor = await get_current_contractor(callback.from_user.id)
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
    contractor = await get_current_contractor(callback.from_user.id)
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

    contractor = await get_current_contractor(message.from_user.id)
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

    contractor = await get_current_contractor(message.from_user.id)
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

    contractor = await get_contractor_by_id(contractor_id)
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
        for admin_id in get_admin_ids():
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
            await backend_client.finalize_payment_validation(validation_id)
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

    contractor = await get_contractor_by_id(contractor_id)
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
    contractors = await get_contractors()
    return await asyncio.to_thread(
        create_contractor, collected, ctype, telegram_id, contractors,
    )


async def _forward_to_admins(raw_text: str, ctype: ContractorType, parsed: dict) -> None:
    """Forward registration data to all admin Telegram IDs."""
    for admin_id in get_admin_ids():
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
    return await asyncio.to_thread(
        parse_registration_data, text, ctype, collected, warnings,
    )
