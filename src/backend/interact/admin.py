"""Admin interaction handlers — invoice generation, batch operations, lookups."""

import base64
import logging
import os
import tempfile
from decimal import Decimal

from backend import (
    create_and_save_invoice,
    export_pdf,
    fetch_articles,
    find_contractor,
    find_contractor_by_id,
    fuzzy_find,
    load_all_contractors,
    load_budget_amounts,
    load_invoices,
    prepare_existing_invoice,
    update_invoice_status,
    update_legium_link,
)
from backend.config import ADMIN_TELEGRAM_TAG
from backend.interact.helpers import (
    ROLE_LABELS,
    InteractContext,
    Payload,
    file_msg,
    invoice_admin_data,
    msg,
    prev_month,
    respond,
    side_msg,
)
from backend.models import (
    Contractor,
    Currency,
    GlobalContractor,
    InvoiceStatus,
    SideMessageTrackType,
)
from backend.models import (
    ResponseDataType as DT,
)
from backend.wiring import create_generate_batch_invoices, create_parse_bank_statement

logger = logging.getLogger(__name__)


def _find_or_suggest(raw_name: str, contractors: list) -> tuple[Contractor | None, dict | None]:
    """Find contractor by name. Returns (contractor, None) or (None, not_found_msg)."""
    contractor = find_contractor(raw_name, contractors)
    if contractor:
        return contractor, None
    matches = fuzzy_find(raw_name, contractors, threshold=0.4)
    if matches:
        return None, msg(data={"type": DT.FUZZY_SUGGESTIONS, "matches": [
            {"name": c.display_name, "type": c.type.value} for c, _ in matches[:5]
        ]})
    return None, msg("Контрагент не найден.")


def handle_generate(payload: Payload, ctx: InteractContext) -> dict:  # noqa: PLR0911 — guard clauses
    progress = ctx.get("progress")
    text = payload.get("text", "").strip()
    if not text:
        return respond([msg("Использование: /generate <имя контрагента>")])

    debug = text.lower().startswith("debug ")
    query = text[6:].strip() if debug else text

    contractors = load_all_contractors()
    contractor, not_found = _find_or_suggest(query, contractors)
    if not contractor:
        return respond([not_found])

    month = prev_month()
    budget_amounts = load_budget_amounts(month)
    articles = fetch_articles(contractor, month)

    name_lower = contractor.display_name.lower().strip()
    budget_entry = budget_amounts.get(name_lower)
    if not budget_entry:
        return respond([msg(f"Контрагент {contractor.display_name} не найден в бюджетной таблице за {month}.")])

    eur, rub, _note = budget_entry
    amount_int = eur if contractor.currency == Currency.EUR else rub
    if not amount_int:
        return respond([msg(f"Сумма для {contractor.display_name} за {month} не указана в бюджетной таблице.")])

    if progress:
        progress.emit("generate_invoice", f"Генерирую документ для {contractor.display_name}")
    try:
        result = create_and_save_invoice(contractor, month, Decimal(str(amount_int)), articles, debug=debug)
    except Exception as e:
        logger.exception("Generate failed for %s", contractor.display_name)
        return respond([msg(f"Ошибка генерации: {e}")])

    pdf_bytes = result.pdf_bytes
    filename = f"{contractor.display_name}+Unsigned.pdf"
    tg_info = f"tg: {contractor.telegram}" if contractor.telegram else "tg id not found"

    if debug:
        return respond([file_msg(pdf_bytes, filename, f"[DEBUG] {contractor.display_name} ({tg_info})")])

    if isinstance(contractor, GlobalContractor):
        return respond([
            file_msg(pdf_bytes, filename, f"Документ для {contractor.display_name}"),
            msg("Проформа готова. Отправьте контрагенту на подпись."),
        ])

    # RUB invoice — send with legium tracking
    return respond([{
        "data": invoice_admin_data(contractor, month, amount_int),
        "file_b64": file_msg(pdf_bytes, filename)["file_b64"],
        "filename": filename,
        "track": {"type": SideMessageTrackType.ADMIN_REPLY,
                  "contractor_telegram": contractor.telegram or "",
                  "contractor_id": contractor.id},
    }])


def handle_articles(payload: Payload, _ctx: InteractContext) -> dict:
    text = payload.get("text", "").strip()
    if not text:
        return respond([msg("Использование: /articles <имя> [YYYY-MM]")])

    parts = text.rsplit(None, 1)
    if len(parts) == 2 and len(parts[1]) >= 6 and parts[1][:4].isdigit() and "-" in parts[1]:
        raw_name, month = parts[0], parts[1]
    else:
        raw_name, month = text, prev_month()

    contractors = load_all_contractors()
    contractor, not_found = _find_or_suggest(raw_name, contractors)
    if not contractor:
        return respond([not_found])

    articles = fetch_articles(contractor, month)
    if not articles:
        return respond([msg(f"У {contractor.display_name} нет публикаций за {month}.")])

    return respond([msg(data={
        "type": DT.ARTICLES_LIST,
        "name": contractor.display_name,
        "role": ROLE_LABELS.get(contractor.role_code, contractor.role_code.value),
        "month": month,
        "count": len(articles),
        "article_ids": [a.article_id for a in articles],
    })])


def handle_lookup(payload: Payload, _ctx: InteractContext) -> dict:
    text = payload.get("text", "").strip()
    if not text:
        return respond([msg("Использование: /lookup <имя>")])

    contractors = load_all_contractors()
    contractor, not_found = _find_or_suggest(text, contractors)
    if not contractor:
        return respond([not_found])

    return respond([msg(data={
        "type": DT.CONTRACTOR_INFO,
        "name": contractor.display_name,
        "contractor_type": contractor.type.value,
        "role": ROLE_LABELS.get(contractor.role_code, contractor.role_code.value),
        "mags": contractor.mags or "",
        "email": contractor.email or "",
        "telegram_linked": bool(contractor.telegram),
        "invoice_number": contractor.invoice_number,
        "has_bank_data": bool(contractor.bank_name and contractor.bank_account),
    })])


def handle_batch_generate(payload: Payload, ctx: InteractContext) -> dict:
    progress = ctx.get("progress")
    debug = "debug" in payload.get("text", "").lower().split()
    month = prev_month()
    contractors = load_all_contractors()

    def _on_batch_progress(done: int, total: int) -> None:
        if progress:
            progress.emit("batch_progress", f"Генерирую счета: {done}/{total}")

    if progress:
        progress.emit("batch_start", f"Запускаю генерацию за {month}")
    try:
        batch_result = create_generate_batch_invoices().execute(
            contractors, month, debug, on_progress=_on_batch_progress)
    except ValueError as e:
        return respond([msg(str(e))])

    if not batch_result.total:
        return respond([msg(f"Нет новых счетов для генерации за {month}.")])

    prefix = "[DEBUG] " if debug else ""
    counts = batch_result.counts

    messages = [msg(data={
        "type": DT.OPERATION_SUMMARY,
        "header": f"{prefix}Генерация за {month} завершена.",
        "counts": counts,
        "total_generated": sum(counts.values()),
        "errors": list(batch_result.errors),
    })]

    # Send individual PDFs
    for pdf_bytes, contractor, invoice in batch_result.generated:
        tg_info = f"tg: {contractor.telegram}" if contractor.telegram else "tg id not found"
        filename = f"{contractor.display_name}+Unsigned.pdf"

        if debug:
            messages.append(file_msg(pdf_bytes, filename,
                                     f"[DEBUG] {contractor.display_name} ({tg_info})"))
        elif contractor.currency == Currency.RUB:
            fname = f"СчетОферта_{contractor.display_name}_{month}.pdf"
            messages.append({
                "data": invoice_admin_data(contractor, month, invoice.amount),
                "file_b64": file_msg(pdf_bytes, fname)["file_b64"],
                "filename": fname,
                "track": {"type": SideMessageTrackType.ADMIN_REPLY,
                          "contractor_telegram": contractor.telegram or "",
                          "contractor_id": contractor.id},
            })

    return respond(messages)


def handle_send_global(payload: Payload, _ctx: InteractContext) -> dict:
    debug = "debug" in payload.get("text", "").lower().split()
    month = prev_month()
    invoices = load_invoices(month)
    draft_global = [inv for inv in invoices if inv.status == InvoiceStatus.DRAFT and inv.currency == Currency.EUR]

    if not draft_global:
        return respond([msg(f"Нет неотправленных глобальных счетов за {month}.")])

    contractors = load_all_contractors()
    sent_count = 0
    errors = []
    messages = []
    sides = []

    for inv in draft_global:
        contractor = find_contractor_by_id(inv.contractor_id, contractors)
        if not contractor:
            errors.append(f"{inv.contractor_id}: контрагент не найден")
            continue
        if not inv.doc_id:
            errors.append(f"{contractor.display_name}: нет doc_id для экспорта PDF")
            continue
        try:
            pdf_bytes = export_pdf(inv.doc_id)
        except Exception as e:
            errors.append(f"{contractor.display_name}: ошибка экспорта PDF ({e})")
            continue

        filename = f"{contractor.display_name}+Unsigned.pdf"

        if debug:
            tg_info = f"tg: {contractor.telegram}" if contractor.telegram else "tg id not found"
            messages.append(file_msg(pdf_bytes, filename,
                                     f"[DEBUG] {contractor.display_name} ({tg_info})"))
        else:
            if not contractor.telegram:
                errors.append(f"{contractor.display_name}: не привязан к Telegram")
                continue
            sides.append(side_msg(
                int(contractor.telegram), file=(pdf_bytes, filename),
                text="Ваша проформа. Пожалуйста, подпишите и отправьте обратно в этот чат.",
            ))

        update_invoice_status(inv.contractor_id, month, InvoiceStatus.SENT)
        sent_count += 1

    prefix = "[DEBUG] " if debug else ""
    messages.insert(0, msg(data={
        "type": DT.OPERATION_SUMMARY,
        "header": f"{prefix}Отправлено {sent_count} глобальных счетов за {month}.",
        "errors": errors,
    }))
    return respond(messages, side_messages=sides)


def handle_send_legium(payload: Payload, _ctx: InteractContext) -> dict:
    debug = "debug" in payload.get("text", "").lower().split()
    month = prev_month()
    invoices = load_invoices(month)
    pending = [inv for inv in invoices if inv.legium_link and inv.status == InvoiceStatus.DRAFT]

    if not pending:
        return respond([msg(f"Нет неотправленных ссылок на Легиум за {month}.")])

    contractors = load_all_contractors()
    sent_count = 0
    errors = []
    messages = []
    sides = []

    for inv in pending:
        contractor = find_contractor_by_id(inv.contractor_id, contractors)
        if not contractor:
            errors.append(f"{inv.contractor_id}: контрагент не найден")
            continue

        if debug:
            tg_info = f"tg: {contractor.telegram}" if contractor.telegram else "tg id not found"
            messages.append(msg(f"[DEBUG] {contractor.display_name} ({tg_info})\n{inv.legium_link}"))
        else:
            if not contractor.telegram:
                errors.append(f"{contractor.display_name}: не привязан к Telegram")
                continue
            caption = (f"Ссылка на Легиум:\n\n{inv.legium_link}\n\n"
                       f"Перейдите по ссылке и подпишите. "
                       f"Если в документе есть ошибка — напишите {ADMIN_TELEGRAM_TAG}.")
            prepared = prepare_existing_invoice(contractor, month)
            if prepared:
                filename = f"{contractor.display_name}+Unsigned.pdf"
                sides.append(side_msg(
                    int(contractor.telegram), text=caption,
                    file=(prepared.pdf_bytes, filename),
                ))
            else:
                sides.append(side_msg(int(contractor.telegram), text=caption))

        update_invoice_status(inv.contractor_id, month, InvoiceStatus.SENT)
        sent_count += 1

    prefix = "[DEBUG] " if debug else ""
    messages.insert(0, msg(data={
        "type": DT.OPERATION_SUMMARY,
        "header": f"{prefix}Отправлено {sent_count} ссылок на Легиум за {month}.",
        "errors": errors,
    }))
    return respond(messages, side_messages=sides)


def handle_orphans(_payload: Payload, _ctx: InteractContext) -> dict:
    month = prev_month()
    contractors = load_all_contractors()
    budget_amounts = load_budget_amounts(month)
    contractor_names = {c.display_name.lower().strip() for c in contractors}
    orphans = sorted(n for n in budget_amounts if n not in contractor_names)
    if not orphans:
        return respond([msg(f"Все записи в бюджете за {month} совпадают с контрагентами.")])
    return respond([msg(data={
        "type": DT.ORPHAN_LIST,
        "month": month,
        "orphans": orphans,
    })])


def handle_upload_statement(payload: Payload, ctx: InteractContext) -> dict:
    progress = ctx.get("progress")
    file_b64 = payload.get("file_b64")
    rate_str = payload.get("rate", "")
    if not file_b64 or not rate_str:
        return respond([msg("Прикрепите CSV-файл банковской выписки с подписью:\n"
                           "/upload_to_airtable <курс AED→RUB>")])
    try:
        rate = float(rate_str)
    except ValueError:
        return respond([msg("Прикрепите CSV-файл банковской выписки с подписью:\n"
                           "/upload_to_airtable <курс AED→RUB>")])

    file_bytes = base64.b64decode(file_b64)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        if progress:
            progress.emit("parse_statement", "Обрабатываю выписку")
        uc = create_parse_bank_statement()
        expenses = uc.execute(tmp_path, rate, upload=True)
        review_count = sum(1 for e in expenses if e.comment == "NEEDS REVIEW")
        return respond([msg(data={
            "type": DT.UPLOAD_RESULT,
            "count": len(expenses),
            "review_count": review_count,
        })])
    except Exception as e:
        logger.exception("Airtable upload failed")
        return respond([msg(f"Ошибка загрузки: {e}")])
    finally:
        if tmp_path:
            os.unlink(tmp_path)


def handle_legium_reply(payload: Payload, _ctx: InteractContext) -> dict:
    """Admin replied to an invoice message with a legium URL."""
    url = payload.get("text", "").strip()
    contractor_id = payload.get("contractor_id", "")
    contractor_telegram = payload.get("contractor_telegram", "")
    month = prev_month()

    contractors = load_all_contractors()
    contractor = find_contractor_by_id(contractor_id, contractors)

    if contractor_telegram:
        caption = (f"Ссылка на Легиум:\n\n{url}\n\n"
                   f"Перейдите по ссылке и подпишите. "
                   f"Если в документе есть ошибка — напишите {ADMIN_TELEGRAM_TAG}.")
        update_legium_link(contractor_id, month, url)
        sides = []
        prepared = prepare_existing_invoice(contractor, month) if contractor else None
        if prepared:
            filename = f"{contractor.display_name}+Unsigned.pdf"
            sides.append(side_msg(int(contractor_telegram), text=caption,
                                  file=(prepared.pdf_bytes, filename)))
        else:
            sides.append(side_msg(int(contractor_telegram), text=caption))
        return respond([msg("Ссылка отправлена контрагенту.")], side_messages=sides)
    update_legium_link(contractor_id, month, url, mark_sent=False)
    return respond([msg(
        "Контрагент не привязан к Telegram. "
        "Ссылка сохранена — отправится через /send_legium_links."
    )])
