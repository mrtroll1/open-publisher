"""Admin interaction handlers."""

import base64
import logging
import os
import tempfile
from decimal import Decimal

from backend.commands.invoice.generate import GenerateInvoice
from backend.commands.invoice.prepare import prepare_existing_invoice
from backend.config import ADMIN_TELEGRAM_TAG
from backend.infrastructure.gateways.docs_gateway import DocsGateway
from backend.infrastructure.gateways.republic_gateway import RepublicGateway
from backend.infrastructure.repositories.sheets.budget_repo import load_all_amounts
from backend.infrastructure.repositories.sheets.contractor_repo import (
    find_contractor,
    find_contractor_by_id,
    fuzzy_find,
    load_all_contractors,
)
from backend.infrastructure.repositories.sheets.invoice_repo import (
    load_invoices,
    update_invoice_status,
    update_legium_link,
)
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
    ContractorType,
    Currency,
    GlobalContractor,
    InvoiceStatus,
    SideMessageTrackType,
)
from backend.models import ResponseDataType as DT
from backend.wiring import create_generate_batch_invoices, create_parse_bank_statement

logger = logging.getLogger(__name__)


class AdminHandlers:

    # ── Public handlers ──

    def generate(self, payload: Payload, ctx: InteractContext) -> dict:
        text = payload.get("text", "").strip()
        if not text:
            return respond([msg("Использование: /generate <имя контрагента>")])
        debug = text.lower().startswith("debug ")
        query = text[6:].strip() if debug else text
        contractor, err = self._find_or_suggest(query)
        if not contractor:
            return respond([err])
        return self._run_generate(contractor, debug, ctx.get("progress"))

    def articles(self, payload: Payload, _ctx: InteractContext) -> dict:
        text = payload.get("text", "").strip()
        if not text:
            return respond([msg("Использование: /articles <имя> [YYYY-MM]")])
        raw_name, month = self._parse_name_month(text)
        contractor, err = self._find_or_suggest(raw_name)
        if not contractor:
            return respond([err])
        return self._format_articles(contractor, month)

    def lookup(self, payload: Payload, _ctx: InteractContext) -> dict:
        text = payload.get("text", "").strip()
        if not text:
            return respond([msg("Использование: /lookup <имя>")])
        contractor, err = self._find_or_suggest(text)
        if not contractor:
            return respond([err])
        return respond([msg(data=self._contractor_info(contractor))])

    def batch_generate(self, payload: Payload, ctx: InteractContext) -> dict:
        progress = ctx.get("progress")
        debug = "debug" in payload.get("text", "").lower().split()
        month = prev_month()
        if progress:
            progress.emit("batch_start", f"Запускаю генерацию за {month}")
        batch_result = self._run_batch(month, debug, progress)
        if isinstance(batch_result, dict):
            return batch_result
        return self._format_batch(batch_result, month, debug)

    def send_global(self, payload: Payload, _ctx: InteractContext) -> dict:
        debug = "debug" in payload.get("text", "").lower().split()
        month = prev_month()
        invoices = load_invoices(month)
        drafts = [inv for inv in invoices if inv.status == InvoiceStatus.DRAFT and inv.currency == Currency.EUR]
        if not drafts:
            return respond([msg(f"Нет неотправленных глобальных счетов за {month}.")])
        return self._send_global_batch(drafts, month, debug)

    def send_legium(self, payload: Payload, _ctx: InteractContext) -> dict:
        debug = "debug" in payload.get("text", "").lower().split()
        month = prev_month()
        invoices = load_invoices(month)
        pending = [inv for inv in invoices if inv.legium_link and inv.status == InvoiceStatus.DRAFT]
        if not pending:
            return respond([msg(f"Нет неотправленных ссылок на Легиум за {month}.")])
        return self._send_legium_batch(pending, month, debug)

    def orphans(self, _payload: Payload, _ctx: InteractContext) -> dict:
        month = prev_month()
        contractors = load_all_contractors()
        budget = load_all_amounts(month)
        names = {c.display_name.lower().strip() for c in contractors}
        orphan_list = sorted(n for n in budget if n not in names)
        if not orphan_list:
            return respond([msg(f"Все записи в бюджете за {month} совпадают с контрагентами.")])
        return respond([msg(data={"type": DT.ORPHAN_LIST, "month": month, "orphans": orphan_list})])

    def upload_statement(self, payload: Payload, ctx: InteractContext) -> dict:
        file_b64 = payload.get("file_b64")
        rate_str = payload.get("rate", "")
        if not file_b64 or not rate_str:
            return self._upload_usage()
        try:
            rate = float(rate_str)
        except ValueError:
            return self._upload_usage()
        return self._process_statement(base64.b64decode(file_b64), rate, ctx.get("progress"))

    def remind_receipts(self, _payload: Payload, _ctx: InteractContext) -> dict:
        month = prev_month()
        invoices = load_invoices(month)
        contractors = load_all_contractors()
        missing = []
        for inv in invoices:
            if inv.receipt_url or inv.currency != Currency.RUB:
                continue
            c = find_contractor_by_id(inv.contractor_id, contractors)
            if not c or c.type != ContractorType.SAMOZANYATY:
                continue
            if inv.status not in (InvoiceStatus.SENT, InvoiceStatus.SIGNED, InvoiceStatus.PAID):
                continue
            missing.append(c)
        if not missing:
            return respond([msg(f"Все чеки за {month} получены (или нет подходящих счетов).")])
        sides = []
        names = []
        for c in missing:
            names.append(c.display_name)
            if c.telegram:
                sides.append(side_msg(
                    int(c.telegram),
                    text=f"Напоминание: пожалуйста, отправьте чек за {month}. "
                         "Отправьте фото или PDF чека в этот чат.",
                ))
        summary = f"Напоминание отправлено ({len(sides)} из {len(missing)}):\n"
        summary += "\n".join(f"  - {n}" for n in names)
        return respond([msg(summary)], side_messages=sides)

    def legium_reply(self, payload: Payload, _ctx: InteractContext) -> dict:
        url = payload.get("text", "").strip()
        contractor_id = payload.get("contractor_id", "")
        contractor_telegram = payload.get("contractor_telegram", "")
        month = prev_month()
        contractors = load_all_contractors()
        contractor = find_contractor_by_id(contractor_id, contractors) if contractor_id else None
        if not contractor:
            name = payload.get("contractor_name", "")
            contractor = find_contractor(name, contractors) if name else None
        if contractor:
            contractor_id = contractor_id or contractor.id
            contractor_telegram = contractor_telegram or contractor.telegram or ""
        if not contractor_id:
            return respond([msg("Контрагент не найден.")])
        if not contractor_telegram:
            update_legium_link(contractor_id, month, url, mark_sent=False)
            return respond([msg("Контрагент не привязан к Telegram. "
                               "Ссылка сохранена — отправится через /send_legium_links.")])
        return self._send_legium_reply(contractor, contractor_id, contractor_telegram, month, url)

    # ── Private helpers ──

    def _find_or_suggest(self, raw_name):
        contractors = load_all_contractors()
        contractor = find_contractor(raw_name, contractors)
        if contractor:
            return contractor, None
        matches = fuzzy_find(raw_name, contractors, threshold=0.4)
        if matches:
            suggestions = [{"name": c.display_name, "type": c.type.value} for c, _ in matches[:5]]
            return None, msg(data={"type": DT.FUZZY_SUGGESTIONS, "matches": suggestions})
        return None, msg("Контрагент не найден.")

    def _budget_amount(self, contractor, month):
        budget = load_all_amounts(month)
        entry = budget.get(contractor.display_name.lower().strip())
        if not entry:
            return None, f"Контрагент {contractor.display_name} не найден в бюджетной таблице за {month}."
        eur, rub, _ = entry
        amount = eur if contractor.currency == Currency.EUR else rub
        if not amount:
            return None, f"Сумма для {contractor.display_name} за {month} не указана в бюджетной таблице."
        return amount, None

    def _rub_invoice_msg(self, contractor, month, amount, pdf_bytes, filename):
        return {
            "data": invoice_admin_data(contractor, month, amount),
            "file_b64": file_msg(pdf_bytes, filename)["file_b64"],
            "filename": filename,
            "track": {"type": SideMessageTrackType.ADMIN_REPLY,
                      "contractor_telegram": contractor.telegram or "",
                      "contractor_id": contractor.id},
        }

    def _parse_name_month(self, text):
        parts = text.rsplit(None, 1)
        if len(parts) == 2 and len(parts[1]) >= 6 and parts[1][:4].isdigit() and "-" in parts[1]:
            return parts[0], parts[1]
        return text, prev_month()

    def _legium_caption(self, link):
        return (f"Ссылка на Легиум:\n\n{link}\n\n"
                f"Перейдите по ссылке и подпишите. "
                f"Если в документе есть ошибка — напишите {ADMIN_TELEGRAM_TAG}.")

    def _summary_response(self, label, sent, month, debug, errors, messages, sides):  # noqa: PLR0913
        prefix = "[DEBUG] " if debug else ""
        messages.insert(0, msg(data={
            "type": DT.OPERATION_SUMMARY,
            "header": f"{prefix}Отправлено {sent} {label} за {month}.",
            "errors": errors,
        }))
        return respond(messages, side_messages=sides)

    def _run_generate(self, contractor, debug, progress):
        month = prev_month()
        amount, err = self._budget_amount(contractor, month)
        if not amount:
            return respond([msg(err)])
        if progress:
            progress.emit("generate_invoice", f"Генерирую документ для {contractor.display_name}")
        result = self._create_invoice(contractor, month, amount, debug=debug)
        if isinstance(result, dict):
            return result
        return self._format_generate_result(result, contractor, month, amount, debug)

    def _create_invoice(self, contractor, month, amount, *, debug=False):
        articles = RepublicGateway().fetch_articles(contractor, month)
        try:
            return GenerateInvoice().create_and_save(
                contractor, month, Decimal(str(amount)), articles, debug=debug)
        except Exception as e:
            logger.exception("Generate failed for %s", contractor.display_name)
            return respond([msg(f"Ошибка генерации: {e}")])

    def _format_generate_result(self, result, contractor, month, amount, debug):
        pdf_bytes = result.pdf_bytes
        filename = f"{contractor.display_name}+Unsigned.pdf"
        if debug:
            tg_info = f"tg: {contractor.telegram}" if contractor.telegram else "tg id not found"
            return respond([file_msg(pdf_bytes, filename, f"[DEBUG] {contractor.display_name} ({tg_info})")])
        if isinstance(contractor, GlobalContractor):
            return respond([file_msg(pdf_bytes, filename, f"Документ для {contractor.display_name}"),
                            msg("Проформа готова. Отправьте контрагенту на подпись.")])
        return respond([self._rub_invoice_msg(contractor, month, amount, pdf_bytes, filename)])

    def _format_articles(self, contractor, month):
        articles = RepublicGateway().fetch_articles(contractor, month)
        if not articles:
            return respond([msg(f"У {contractor.display_name} нет публикаций за {month}.")])
        return respond([msg(data={
            "type": DT.ARTICLES_LIST, "name": contractor.display_name,
            "role": ROLE_LABELS.get(contractor.role_code, contractor.role_code.value),
            "month": month, "count": len(articles),
            "article_ids": [a.article_id for a in articles],
        })])

    def _contractor_info(self, c):
        return {
            "type": DT.CONTRACTOR_INFO, "name": c.display_name,
            "contractor_type": c.type.value,
            "role": ROLE_LABELS.get(c.role_code, c.role_code.value),
            "mags": c.mags or "", "email": c.email or "",
            "telegram_linked": bool(c.telegram),
            "invoice_number": c.invoice_number,
            "has_bank_data": bool(c.bank_name and c.bank_account),
        }

    def _run_batch(self, month, debug, progress):
        contractors = load_all_contractors()

        def on_progress(done, total):
            if progress:
                progress.emit("batch_progress", f"Генерирую счета: {done}/{total}")

        try:
            return create_generate_batch_invoices().execute(
                contractors, month, debug, on_progress=on_progress)
        except ValueError as e:
            return respond([msg(str(e))])

    def _format_batch(self, batch_result, month, debug):
        if not batch_result.total:
            return respond([msg(f"Нет новых счетов для генерации за {month}.")])
        summary = self._batch_summary(month, debug, batch_result)
        items = [m for r in batch_result.generated if (m := self._batch_item_msg(r, month, debug))]
        return respond([summary, *items])

    def _batch_summary(self, month, debug, batch_result):
        prefix = "[DEBUG] " if debug else ""
        return msg(data={
            "type": DT.OPERATION_SUMMARY,
            "header": f"{prefix}Генерация за {month} завершена.",
            "counts": batch_result.counts,
            "total_generated": sum(batch_result.counts.values()),
            "errors": list(batch_result.errors),
        })

    def _batch_item_msg(self, generated_item, month, debug):
        pdf_bytes, contractor, invoice = generated_item
        filename = f"{contractor.display_name}+Unsigned.pdf"
        if debug:
            tg_info = f"tg: {contractor.telegram}" if contractor.telegram else "tg id not found"
            return file_msg(pdf_bytes, filename, f"[DEBUG] {contractor.display_name} ({tg_info})")
        if contractor.currency == Currency.RUB:
            fname = f"СчетОферта_{contractor.display_name}_{month}.pdf"
            return self._rub_invoice_msg(contractor, month, invoice.amount, pdf_bytes, fname)
        return None

    def _send_global_batch(self, drafts, month, debug):
        contractors = load_all_contractors()
        messages, sides, errors, sent = [], [], [], 0
        for inv in drafts:
            contractor = find_contractor_by_id(inv.contractor_id, contractors)
            err = self._send_one_global(inv, contractor, month, debug, messages, sides)
            if err:
                errors.append(err)
            else:
                sent += 1
        return self._summary_response("глобальных счетов", sent, month, debug, errors, messages, sides)

    def _send_one_global(self, inv, contractor, month, debug, messages, sides):  # noqa: PLR0913
        if not contractor:
            return f"{inv.contractor_id}: контрагент не найден"
        if not inv.doc_id:
            return f"{contractor.display_name}: нет doc_id для экспорта PDF"
        try:
            pdf_bytes = DocsGateway().export_pdf(inv.doc_id)
        except Exception as e:
            return f"{contractor.display_name}: ошибка экспорта PDF ({e})"
        return self._deliver_global(contractor, pdf_bytes, month, debug, messages, sides)

    def _deliver_global(self, contractor, pdf_bytes, month, debug, messages, sides):  # noqa: PLR0913
        filename = f"{contractor.display_name}+Unsigned.pdf"
        if debug:
            tg_info = f"tg: {contractor.telegram}" if contractor.telegram else "tg id not found"
            messages.append(file_msg(pdf_bytes, filename, f"[DEBUG] {contractor.display_name} ({tg_info})"))
        elif not contractor.telegram:
            return f"{contractor.display_name}: не привязан к Telegram"
        else:
            sides.append(side_msg(int(contractor.telegram), file=(pdf_bytes, filename),
                                  text="Ваша проформа. Пожалуйста, подпишите и отправьте обратно в этот чат."))
        update_invoice_status(contractor.id, month, InvoiceStatus.SENT)
        return None

    def _send_legium_batch(self, pending, month, debug):
        contractors = load_all_contractors()
        messages, sides, errors, sent = [], [], [], 0
        for inv in pending:
            contractor = find_contractor_by_id(inv.contractor_id, contractors)
            err = self._send_one_legium(inv, contractor, month, debug, messages, sides)
            if err:
                errors.append(err)
            else:
                sent += 1
        return self._summary_response("ссылок на Легиум", sent, month, debug, errors, messages, sides)

    def _send_one_legium(self, inv, contractor, month, debug, messages, sides):  # noqa: PLR0913
        if not contractor:
            return f"{inv.contractor_id}: контрагент не найден"
        if debug:
            tg_info = f"tg: {contractor.telegram}" if contractor.telegram else "tg id not found"
            messages.append(msg(f"[DEBUG] {contractor.display_name} ({tg_info})\n{inv.legium_link}"))
        elif not contractor.telegram:
            return f"{contractor.display_name}: не привязан к Telegram"
        else:
            self._send_legium_to_contractor(contractor, inv, month, sides)
        update_invoice_status(inv.contractor_id, month, InvoiceStatus.SENT)
        return None

    def _send_legium_to_contractor(self, contractor, inv, month, sides):
        caption = self._legium_caption(inv.legium_link)
        prepared = prepare_existing_invoice(contractor, month)
        if prepared:
            filename = f"{contractor.display_name}+Unsigned.pdf"
            sides.append(side_msg(int(contractor.telegram), text=caption,
                                  file=(prepared.pdf_bytes, filename)))
        else:
            sides.append(side_msg(int(contractor.telegram), text=caption))

    def _upload_usage(self):
        return respond([msg("Прикрепите CSV-файл банковской выписки с подписью:\n"
                           "/upload_to_airtable <курс AED→RUB>")])

    def _process_statement(self, file_bytes, rate, progress):
        tmp_path = self._write_temp_csv(file_bytes)
        try:
            if progress:
                progress.emit("parse_statement", "Обрабатываю выписку")
            return self._run_statement_upload(tmp_path, rate)
        finally:
            os.unlink(tmp_path)

    def _write_temp_csv(self, file_bytes):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            tmp.write(file_bytes)
            return tmp.name

    def _run_statement_upload(self, tmp_path, rate):
        try:
            expenses = create_parse_bank_statement().execute(tmp_path, rate, upload=True)
        except Exception as e:
            logger.exception("Airtable upload failed")
            return respond([msg(f"Ошибка загрузки: {e}")])
        review_count = sum(1 for e in expenses if e.comment == "NEEDS REVIEW")
        return respond([msg(data={"type": DT.UPLOAD_RESULT, "count": len(expenses),
                                  "review_count": review_count})])

    def _send_legium_reply(self, contractor, contractor_id, contractor_telegram, month, url):
        caption = self._legium_caption(url)
        update_legium_link(contractor_id, month, url)
        prepared = prepare_existing_invoice(contractor, month) if contractor else None
        if prepared:
            filename = f"{contractor.display_name}+Unsigned.pdf"
            sides = [side_msg(int(contractor_telegram), text=caption,
                              file=(prepared.pdf_bytes, filename))]
        else:
            sides = [side_msg(int(contractor_telegram), text=caption)]
        return respond([msg("Ссылка отправлена контрагенту.")], side_messages=sides)
