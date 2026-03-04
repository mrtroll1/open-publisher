"""Admin command handlers."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from decimal import Decimal

from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile

from common.config import ADMIN_TELEGRAM_IDS
from common.models import (
    Currency,
    GlobalContractor,
    InvoiceStatus,
    RoleCode,
)
from backend import (
    create_and_save_invoice,
    export_pdf,
    fetch_articles,
    find_contractor_by_id,
    load_invoices,
    prepare_existing_invoice,
    read_budget_amounts,
    update_invoice_status,
    update_legium_link,
)
from backend.domain.services.compose_request import _get_retriever
from backend.domain.services.admin_service import (
    _GREETING_PREFIXES,
    classify_draft_reply,
    store_admin_feedback,
)
from backend.domain.use_cases import sync_contractor_entities
from backend.infrastructure.gateways.embedding_gateway import EmbeddingGateway
from backend.wiring import create_compute_budget, create_generate_batch_invoices, create_parse_bank_statement
from telegram_bot import replies
from telegram_bot.bot_helpers import bot, get_contractors, prev_month
from telegram_bot.handler_utils import (
    _admin_reply_map,
    _db,
    _find_contractor_or_suggest,
    _inbox,
    _save_turn,
    _send,
    _send_html,
    _support_draft_map,
    get_contractor_by_id,
    parse_month_arg,
    send_typing,
)

logger = logging.getLogger(__name__)

_ROLE_LABELS = {
    RoleCode.AUTHOR: "автор",
    RoleCode.REDAKTOR: "редактор",
    RoleCode.KORREKTOR: "корректор",
}

__all__ = [
    "cmd_generate",
    "cmd_budget",
    "cmd_generate_invoices",
    "cmd_send_global_invoices",
    "cmd_send_legium_links",
    "cmd_orphan_contractors",
    "cmd_upload_to_airtable",
    "cmd_sync_entities",
    "cmd_chatid",
    "cmd_articles",
    "cmd_lookup",
    "_ROLE_LABELS",
    "handle_admin_reply",
    "_handle_draft_reply",
    "_GREETING_PREFIXES",
]


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

    await send_typing(message.chat.id)

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
    """Routing chain for admin replies: Legium forwarding → support draft → NL reply."""
    reply = message.reply_to_message
    if not reply:
        return

    # 1. Legium forwarding (existing behavior)
    key = (message.chat.id, reply.message_id)
    entry = _admin_reply_map.get(key)
    if entry:
        contractor_tg, contractor_id = entry
        try:
            url = message.text.strip()
            month = prev_month()
            if contractor_tg:
                caption = replies.invoice.legium_link.format(url=url)
                contractor = await get_contractor_by_id(contractor_id)
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
        return

    # 2. Support draft reply
    uid = _support_draft_map.get(key)
    if uid:
        await _handle_draft_reply(message, uid)
        del _support_draft_map[key]
        return

    # 3. Knowledge edit reply
    from telegram_bot.handlers.conversation_handlers import handle_kedit_reply
    if await handle_kedit_reply(message):
        return

    # 4. NL conversation fallback (lazy import to avoid circular dependency)
    from telegram_bot.handlers.conversation_handlers import _handle_nl_reply
    await _handle_nl_reply(message, state)


async def _handle_draft_reply(message: types.Message, uid: str) -> None:
    draft = _inbox.get_pending_support(uid)
    if not draft:
        await message.reply(replies.tech_support.expired)
        return

    text = message.text.strip()
    action = classify_draft_reply(text)

    if action == "replacement":
        await asyncio.to_thread(_inbox.update_and_approve_support, uid, message.text)
        addr = draft.email.reply_to or draft.email.from_addr
        await message.reply(replies.tech_support.replacement_sent.format(addr=addr))
    else:
        await asyncio.to_thread(_inbox.skip_support, uid)
        await asyncio.to_thread(store_admin_feedback, text, "tech_support", _get_retriever())
        await message.reply(replies.tech_support.feedback_noted)


async def cmd_chatid(message: types.Message, state: FSMContext) -> None:
    await message.answer(f"Chat ID: `{message.chat.id}`", parse_mode="Markdown")


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

    await send_typing(message.chat.id)
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

    await _send(message, "\n".join(lines))


async def cmd_budget(message: types.Message, state: FSMContext) -> None:
    """Generate the budget payments sheet."""
    args = message.text.split(maxsplit=1)
    month = parse_month_arg(args)

    await message.answer(replies.admin.budget_generating.format(month=month))
    await send_typing(message.chat.id)

    try:
        uc = create_compute_budget()
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
    await send_typing(message.chat.id)

    contractors = await get_contractors()

    try:
        batch_result = await asyncio.to_thread(
            create_generate_batch_invoices().execute, contractors, month, debug,
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
    await _send(message, "\n\n".join(parts))

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

    await send_typing(message.chat.id)

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
    await _send(message, "\n\n".join(parts))


async def cmd_send_legium_links(message: types.Message, state: FSMContext) -> None:
    """Batch-send legium links to contractors whose invoices have a link but are still DRAFT."""
    debug = "debug" in message.text.lower().split()

    await send_typing(message.chat.id)

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
    await _send(message, "\n\n".join(parts))


async def cmd_orphan_contractors(message: types.Message, state: FSMContext) -> None:
    """Show budget entries that don't match any contractor."""
    await send_typing(message.chat.id)

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
    await send_typing(message.chat.id)

    file = await bot.get_file(message.document.file_id)
    file_bytes = await bot.download_file(file.file_path)

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            tmp.write(file_bytes.read())
            tmp_path = tmp.name

        uc = create_parse_bank_statement()
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


async def cmd_sync_entities(message: types.Message, state: FSMContext) -> None:
    """Sync contractors from Google Sheets into the entities system."""
    await send_typing(message.chat.id)

    contractors = await get_contractors()
    embed = EmbeddingGateway()

    created, updated = await asyncio.to_thread(
        sync_contractor_entities.execute, contractors, _db, embed,
    )

    await message.answer(replies.admin.sync_entities_done.format(created=created, updated=updated))
