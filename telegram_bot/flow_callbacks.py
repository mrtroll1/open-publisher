"""Callback functions for flow declarations.

Each handler receives (message, state) and returns Optional[str]:
  - None  = stay in current state (no transition)
  - "key" = follow the transition mapped to that key
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from decimal import Decimal
from aiogram import types
from aiogram.enums import ChatAction
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery

from common.config import ADMIN_TELEGRAM_IDS, EMAIL_ADDRESS

from common.models import (
    CONTRACTOR_CLASS_BY_TYPE,
    Contractor,
    ContractorType,
    Currency,
    GlobalContractor,
    InvoiceStatus,
    SupportDraft,
)
from backend import (
    bind_telegram_id,
    create_and_save_invoice,
    export_pdf,
    fetch_articles,
    find_contractor,
    find_contractor_by_id,
    find_contractor_by_telegram_id,
    fuzzy_find,
    GenerateBatchInvoices,
    load_invoices,
    next_contractor_id,
    parse_contractor_data,
    plural_ru,
    pop_random_secret_code,
    prepare_existing_invoice,
    read_budget_amounts,
    resolve_amount,
    save_contractor,
    translate_name_to_russian,
    update_invoice_status,
    update_legium_link,
    upload_invoice_pdf,
    validate_contractor_fields,
)
from telegram_bot import replies
from telegram_bot.bot_helpers import bot, get_contractors, is_admin, prev_month

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  /start
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def handle_start(message: types.Message, state: FSMContext) -> None:
    await state.clear()
    if is_admin(message.from_user.id):
        await message.answer(replies.start.admin)
    else:
        await message.answer(replies.start.contractor)


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

    for key, value in parsed.items():
        if isinstance(value, str) and value.strip():
            collected[key] = value.strip()

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
        parts = ["Вот что я уже получил:\n" + "\n".join(filled_lines)]
        if missing:
            parts.append("Ещё нужно: " + ", ".join(missing.values()) + ".")
        if warnings:
            parts.append("\n".join(f"  ⚠ {w}" for w in warnings))
        parts.append("Пришлите исправленные/недостающие данные.")
        await message.answer("\n\n".join(parts))
        return None

    # For Global contractors, translate name to Russian and add as alias
    if ctype == ContractorType.GLOBAL:
        name_en = collected.get("name_en", "")
        if name_en:
            name_ru = await _translate_name_to_russian(name_en)
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

    # Already bound?
    contractor = find_contractor_by_telegram_id(telegram_id, contractors)
    if contractor:
        delivered = await _deliver_existing_invoice(message, contractor)
        if not delivered:
            month = prev_month()
            await message.answer(
                replies.lookup.no_invoices.format(name=contractor.display_name, month=month)
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
            text="Я новый контрагент",
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
    """Catch photos/stickers/etc from Global contractors — remind them to send a PDF."""
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
                caption = f"Документ от {sender_info}:"
                if drive_link:
                    caption += f"\nСохранено на Drive: {drive_link}"
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

    contractors = await get_contractors()
    contractor = find_contractor(query, contractors)

    if not contractor:
        matches = fuzzy_find(query, contractors, threshold=0.4)
        if matches:
            suggestions = "\n".join(
                f"  - {c.display_name} ({c.type.value})" for c, _ in matches[:5]
            )
            await message.answer(replies.lookup.fuzzy_suggestions.format(suggestions=suggestions))
        else:
            await message.answer(replies.lookup.not_found)
        return

    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    month = prev_month()

    budget_amounts = await asyncio.to_thread(read_budget_amounts, month)
    articles = await asyncio.to_thread(fetch_articles, contractor, month)

    name_lower = contractor.display_name.lower().strip()
    budget_entry = budget_amounts.get(name_lower)
    if not budget_entry:
        await message.answer(
            f"Контрагент {contractor.display_name} не найден в бюджетной таблице за {month}."
        )
        return

    eur, rub, _note = budget_entry
    amount_int = eur if contractor.currency == Currency.EUR else rub
    if not amount_int:
        await message.answer(
            f"Сумма для {contractor.display_name} за {month} не указана в бюджетной таблице."
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
    else:
        await message.answer_document(doc, caption=f"Документ для {contractor.display_name}")
        if isinstance(contractor, GlobalContractor):
            await message.answer(replies.admin.proforma_ready)
        else:
            await message.answer(replies.admin.invoice_ready)


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
        await bot.send_message(
            int(contractor_tg),
            replies.invoice.legium_link.format(url=url),
        )
        month = prev_month()
        await asyncio.to_thread(
            update_legium_link, contractor_id, month, url,
        )
        await message.answer(replies.invoice.legium_sent)
        del _admin_reply_map[key]
    except Exception as e:
        await message.answer(replies.invoice.legium_send_error.format(error=e))


async def cmd_budget(message: types.Message, state: FSMContext) -> None:
    """Generate the budget payments sheet."""
    args = message.text.split(maxsplit=1)
    month = args[1].strip() if len(args) > 1 else prev_month()

    await message.answer(replies.admin.budget_generating.format(month=month))
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    try:
        from backend.domain.compute_budget import ComputeBudget
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
    status_msg = await message.answer(f"Генерирую инвойсы за {month}...")

    contractors = await get_contractors()

    try:
        batch_result = await asyncio.to_thread(
            GenerateBatchInvoices().execute, contractors, month, debug,
        )
    except ValueError as e:
        await status_msg.edit_text(str(e))
        return

    if not batch_result.total:
        await status_msg.edit_text(f"Нет новых счетов для генерации за {month}.")
        return

    # Summary message
    prefix = "[DEBUG] " if debug else ""
    counts = batch_result.counts
    parts = [f"{prefix}Генерация за {month} завершена."]
    generated = counts["global"] + counts["samozanyaty"] + counts["ip"]
    if generated:
        parts.append(
            f"Сгенерировано: {counts['global']} global, "
            f"{counts['samozanyaty']} самозанятых, {counts['ip']} ИП"
        )
    else:
        parts.append("Новых счетов не сгенерировано.")
    if batch_result.errors:
        parts.append("Ошибки:\n" + "\n".join(f"  - {e}" for e in batch_result.errors))
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
                if contractor.telegram:
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
    parts = [f"{prefix}Отправлено {sent_count} глобальных счетов за {month}."]
    if errors:
        parts.append("Ошибки:\n" + "\n".join(f"  - {e}" for e in errors))
    await message.answer("\n\n".join(parts))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Private helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

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
            for admin_id in ADMIN_TELEGRAM_IDS:
                try:
                    admin_doc = BufferedInputFile(prepared.pdf_bytes, filename=filename)
                    caption = replies.invoice.legium_admin_caption.format(
                        name=contractor.display_name, type=contractor.type.value,
                        month=month, amount=inv.amount,
                    )
                    sent = await bot.send_document(admin_id, admin_doc, caption=caption)
                    _admin_reply_map[(admin_id, sent.message_id)] = (contractor.telegram, contractor.id)
                except Exception:
                    pass
        else:
            await message.answer(replies.invoice.legium_already_sent)

    return True


async def handle_duplicate_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle inline button press for duplicate contractor selection."""
    data_str = callback.data
    await callback.answer()

    if data_str == "dup:new":
        await callback.message.delete()
        await state.set_state("ContractorStates:waiting_type")
        await callback.message.answer(replies.registration.type_prompt)
        return

    contractor_id = data_str.removeprefix("dup:")
    contractors = await get_contractors()
    contractor = find_contractor_by_id(contractor_id, contractors)
    if not contractor:
        await callback.message.answer(replies.lookup.not_found)
        return

    await callback.message.edit_text(
        f"✓ {contractor.display_name}",
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
                    f"Контрагент {contractor.display_name} привязался к Telegram.",
                )
            except Exception:
                pass
        delivered = await _deliver_existing_invoice(message, contractor)
        if delivered:
            await state.clear()
            return "verified"

        # No pre-generated invoice — check budget sheet and start amount flow
        month = prev_month()
        budget_amounts = await asyncio.to_thread(read_budget_amounts, month)
        articles = await asyncio.to_thread(fetch_articles, contractor, month)
        num_articles = len(articles)

        default_amount_int, explanation = resolve_amount(
            budget_amounts, contractor, num_articles,
        )
        if not default_amount_int:
            await message.answer(replies.registration.no_articles.format(month=month))
            await state.clear()
            return "verified"

        article_ids = [a.article_id for a in articles]
        await state.set_data({
            "invoice_contractor_id": contractor.id,
            "invoice_month": month,
            "invoice_article_ids": article_ids,
            "invoice_default_amount": default_amount_int,
        })
        pub_word = plural_ru(num_articles, "публикация", "публикации", "публикаций") if num_articles else "0 публикаций"
        await message.answer(
            replies.invoice.amount_prompt.format(
                pub_word=pub_word, month=month, explanation=explanation,
            )
        )
        return "invoice"

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

    text = (
        "Ваши данные:\n" + summary + "\n\n"
        "Вы добавлены в систему!"
    )
    if secret_code:
        text += f"\n\nВаш секретный код: *{secret_code}*."
    await message.answer(text)

    if not contractor:
        return "complete"

    # Check budget sheet / articles → start invoice flow
    month = prev_month()
    budget_amounts = await asyncio.to_thread(read_budget_amounts, month)
    articles = await asyncio.to_thread(fetch_articles, contractor, month)
    num_articles = len(articles)

    default_amount_int, explanation = resolve_amount(
        budget_amounts, contractor, num_articles,
    )
    if not default_amount_int:
        await message.answer(replies.registration.no_articles.format(month=month))
        return "complete"

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
        for admin_id in ADMIN_TELEGRAM_IDS:
            try:
                admin_doc = BufferedInputFile(result.pdf_bytes, filename=filename)
                caption = replies.invoice.legium_admin_caption.format(
                    name=contractor.display_name, type=contractor.type.value,
                    month=month, amount=invoice.amount,
                )
                sent = await bot.send_document(admin_id, admin_doc, caption=caption)
                _admin_reply_map[(admin_id, sent.message_id)] = (contractor.telegram, contractor.id)
            except Exception:
                pass

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
            msg = f"Новая регистрация ({ctype.value}):\n\n{raw_text}"
            if parsed:
                formatted = "\n".join(f"  {k}: {v}" for k, v in parsed.items() if v)
                msg += f"\n\nРаспознанные данные:\n{formatted}"
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
        filled = {k: v for k, v in collected.items() if v}
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

    return await asyncio.to_thread(parse_contractor_data, text, fields, context)


async def _translate_name_to_russian(name_en: str) -> str:
    """Translate a name to Russian via LLM."""
    return await asyncio.to_thread(translate_name_to_russian, name_en)


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

    import tempfile
    file = await bot.get_file(message.document.file_id)
    file_bytes = await bot.download_file(file.file_path)

    try:
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            tmp.write(file_bytes.read())
            tmp_path = tmp.name

        from backend.domain.parse_bank_statement import ParseBankStatement
        uc = ParseBankStatement()
        expenses = await asyncio.to_thread(uc.execute, tmp_path, rate, True)

        review_count = sum(1 for e in expenses if e.comment == "NEEDS REVIEW")
        text = replies.admin.upload_done.format(count=len(expenses))
        if review_count:
            text += f"\n⚠ {review_count} записей требуют проверки (NEEDS REVIEW)."
        await message.answer(text)
    except Exception as e:
        logger.exception("Airtable upload failed")
        await message.answer(replies.admin.upload_error.format(error=e))
    finally:
        import os
        os.unlink(tmp_path)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Email support: background listener + callback handler
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

from backend.domain.support_email_service import SupportEmailService

_email_service = SupportEmailService()


async def email_listener_task() -> None:
    """Background task: listen for new emails and send drafts to admin."""
    admin_id = ADMIN_TELEGRAM_IDS[0]
    logger.info("Email listener started for %s", EMAIL_ADDRESS)
    while True:
        try:
            has_new = await asyncio.to_thread(_email_service.wait_for_mail, 300)
            if not has_new:
                continue
            drafts = await asyncio.to_thread(_email_service.fetch_new_drafts)
            for draft in drafts:
                await _send_email_draft(admin_id, draft)
        except Exception as e:
            logger.exception("Email listener error: %s", e)
            await asyncio.sleep(30)


async def _send_email_draft(admin_id: int, draft: SupportDraft) -> None:
    em = draft.email
    sender = em.reply_to or em.from_addr
    body_preview = em.body[:500] + ("..." if len(em.body) > 500 else "")
    header = f"From: {em.from_addr}\n"
    if em.reply_to and em.reply_to != em.from_addr:
        header += f"Reply-To: {em.reply_to}\n"
    text = (
        f"{header}"
        f"Subject: {em.subject}\n\n"
        f"{body_preview}\n\n"
        f"--- Draft reply (can_answer: {draft.can_answer}) ---\n"
        f"{draft.draft_reply}"
    )
    buttons = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Send", callback_data=f"email:send:{em.uid}"),
        InlineKeyboardButton(text="Skip", callback_data=f"email:skip:{em.uid}"),
    ]])
    await bot.send_message(admin_id, text, reply_markup=buttons)


async def handle_email_callback(callback: CallbackQuery) -> None:
    """Handle send/skip button presses for email drafts."""
    await callback.answer()
    parts = callback.data.split(":")
    if len(parts) != 3:
        return
    _, action, uid = parts

    draft = _email_service.get_pending(uid)
    if not draft:
        await callback.message.edit_text("(expired — email already handled)")
        return

    if action == "send":
        await asyncio.to_thread(_email_service.approve, uid)
        await callback.message.edit_text(f"Reply sent to {draft.email.reply_to or draft.email.from_addr}")
    elif action == "skip":
        await asyncio.to_thread(_email_service.skip, uid)
        await callback.message.edit_text(f"Skipped email from {draft.email.from_addr}")
