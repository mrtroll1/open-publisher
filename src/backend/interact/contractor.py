"""Contractor interaction handlers."""

import base64
import logging
import re
from decimal import Decimal
from typing import ClassVar

from backend.commands.budget.redirect import redirect_in_budget, unredirect_in_budget
from backend.commands.contractor.create import ContractorFactory
from backend.commands.contractor.registration import RegistrationParser
from backend.commands.contractor.validate import validate_fields as validate_contractor_fields
from backend.commands.invoice.generate import GenerateInvoice
from backend.commands.invoice.service import DeliveryAction, InvoiceService
from backend.config import ADMIN_TELEGRAM_TAG, PRODUCT_NAME
from backend.infrastructure.gateways.drive_gateway import DriveGateway
from backend.infrastructure.gateways.republic_gateway import RepublicGateway
from backend.infrastructure.repositories.sheets.contractor_repo import (
    bind_telegram_id,
    find_contractor_by_id,
    find_contractor_by_telegram_id,
    fuzzy_find,
    load_all_contractors,
    update_contractor_fields,
)
from backend.infrastructure.repositories.sheets.invoice_repo import (
    delete_invoice,
    update_invoice_status,
)
from backend.infrastructure.repositories.sheets.rules_repo import (
    add_redirect_rule,
    find_redirect_rules_by_target,
    remove_redirect_rule,
)
from backend.interact.helpers import (
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
    CONTRACTOR_CLASS_BY_TYPE,
    ContractorType,
    Currency,
    GlobalContractor,
    InvoiceStatus,
    RoleCode,
    SideMessageTrackType,
)
from backend.models import ResponseDataType as DT

logger = logging.getLogger(__name__)


class ContractorHandlers:

    _TYPE_MAP: ClassVar = {
        "1": ContractorType.SAMOZANYATY, "2": ContractorType.IP, "3": ContractorType.GLOBAL,
        "самозанятый": ContractorType.SAMOZANYATY, "ип": ContractorType.IP, "global": ContractorType.GLOBAL,
    }

    _DATA_PROMPTS: ClassVar = {
        ContractorType.SAMOZANYATY: (
            "Отправьте ваши данные в свободной форме или по пунктам:\n\n"
            "- ФИО\n- Серия и номер паспорта\n- ИНН\n- Адрес\n- Email\n"
            "- Банк, номер счёта (рубли), БИК, корр. счёт\n\n"
            "Можно одним сообщением — я разберусь."
        ),
        ContractorType.IP: (
            "Отправьте ваши данные в свободной форме или по пунктам:\n\n"
            "- ФИО\n- ОГРНИП\n- Серия и номер паспорта\n"
            "- Кем выдан, дата выдачи, код подразделения\n"
            "- Email\n- Банк, номер счёта (рубли), БИК, корр. счёт\n\n"
            "Можно одним сообщением — я разберусь."
        ),
        ContractorType.GLOBAL: (
            "Отправьте ваши данные в свободной форме или по пунктам:\n\n"
            "- Полное имя (латиницей)\n- Адрес\n- Email\n"
            "- Название банка, IBAN или номер счёта, BIC/SWIFT (если есть)\n\n"
            "Можно одним сообщением — я разберусь."
        ),
    }

    # ── Shared helpers ──

    def _get_contractor(self, user_id):
        contractors = load_all_contractors()
        return find_contractor_by_telegram_id(user_id, contractors), contractors

    def _greeting(self):
        return respond([msg(
            "Здравствуйте! Я бот для оформления оплаты.\n\n"
            f"Под каким именем/псевдонимом вы работаете на {PRODUCT_NAME}?"
        )], fsm_state=None)

    def _menu_keyboard(self, contractor):
        rows = [
            [{"text": "Подписать договор для выплат", "data": "menu:contract"}],
            [{"text": "Обновить мои платежные данные", "data": "menu:update"}],
        ]
        if contractor.role_code == RoleCode.REDAKTOR:
            rows.append([{"text": "Настроить, за кого я получаю деньги", "data": "menu:editor"}])
        return rows

    def _menu_response(self, contractor):
        return respond(
            [msg("Что хотите сделать?", keyboard=self._menu_keyboard(contractor))],
            fsm_state=None,
        )

    def _dup_label(self, c):
        alias = c.aliases[0] if c.aliases else ""
        return f"{alias} ({c.display_name})" if alias and alias != c.display_name else c.display_name

    def _editor_keyboard(self, rules):
        rows = [[{"text": f"❌ {r.source_name}", "data": f"esrc:rm:{r.source_name}"}] for r in rules]
        if rules:
            text = "Сейчас вы получаете деньги за:\n" + "".join(f"\n  - {r.source_name}" for r in rules)
        else:
            text = "У вас пока нет привязанных авторов."
        rows += [
            [{"text": "Добавить автора", "data": "esrc:add"}],
            [{"text": "← Назад", "data": "esrc:back"}],
        ]
        return text, rows

    def _show_editor_sources(self, contractor):
        rules = find_redirect_rules_by_target(contractor.id)
        text, keyboard = self._editor_keyboard(rules)
        return respond([msg(text, keyboard=keyboard)])

    def _type_selection_prompt(self):
        return msg("Какой у вас статус?\n\n"
                   "1. Самозанятый (хочу получать в рублях)\n"
                   "2. ИП (хочу получать в рублях)\n"
                   "3. Зарубежный контрагент (хочу получать в евро)\n\n"
                   "Отправьте цифру (1, 2 или 3).")

    def _no_publications(self, month):
        return respond([msg(f"Публикаций за {month} не найдено.\n"
                           f"Если это ошибка — напишите {ADMIN_TELEGRAM_TAG}.")])

    # ── Invoice flow ──

    def _start_invoice_flow(self, contractor, month, fsm_data):
        data = InvoiceService().prepare_new_data(contractor, month)
        if not data:
            return None
        new_data = {**fsm_data, "invoice_contractor_id": contractor.id,
                    "invoice_month": month, "invoice_article_ids": data.article_ids,
                    "invoice_default_amount": data.default_amount}
        return respond([msg(data={"type": DT.INVOICE_PROMPT, "pub_word": data.pub_word,
                                  "month": month, "explanation": data.explanation,
                                  "default_amount": data.default_amount})],
                       fsm_state="waiting_amount", fsm_data=new_data)

    def _deliver_existing_invoice(self, contractor, month, admin_ids):
        result = InvoiceService().resolve_existing(contractor, month)
        if not result:
            return None
        pdf = result.prepared.pdf_bytes
        filename = f"{contractor.display_name}+Unsigned.pdf"
        return self._dispatch_delivery(result.action, result.prepared.invoice,
                                       contractor, month, pdf, filename, admin_ids)

    def _dispatch_delivery(self, action, inv, contractor, month, pdf, filename, admin_ids):  # noqa: PLR0913
        if action == DeliveryAction.SEND_PROFORMA:
            return self._send_proforma(inv, month, pdf, filename)
        if action == DeliveryAction.PROFORMA_ALREADY_SENT:
            return respond([msg("Ваша проформа уже отправлена, проверьте историю чата.")])
        if action == DeliveryAction.SEND_RUB_WITH_LEGIUM:
            return self._send_rub_legium(inv, month, pdf, filename)
        if action == DeliveryAction.SEND_RUB_DRAFT:
            return self._send_rub_draft(contractor, inv, month, pdf, filename, admin_ids)
        if action == DeliveryAction.RUB_ALREADY_SENT:
            return respond([msg("Ссылка на Легиум уже отправлена, проверьте историю чата.")])
        return None

    def _send_proforma(self, inv, month, pdf, filename):
        update_invoice_status(inv.contractor_id, month, InvoiceStatus.SENT)
        return respond([file_msg(pdf, filename,
                                 "Ваша проформа. Пожалуйста, подпишите и отправьте обратно в этот чат.")])

    def _send_rub_legium(self, inv, month, pdf, filename):
        if inv.status == InvoiceStatus.DRAFT:
            update_invoice_status(inv.contractor_id, month, InvoiceStatus.SENT)
        caption = (f"Ссылка на Легиум:\n\n{inv.legium_link}\n\n"
                   f"Перейдите по ссылке и подпишите. "
                   f"Если в документе есть ошибка — напишите {ADMIN_TELEGRAM_TAG}.")
        return respond([file_msg(pdf, filename, caption)])

    def _send_rub_draft(self, contractor, inv, month, pdf, filename, admin_ids):  # noqa: PLR0913
        caption = "Ваш счёт-оферта. Скоро пришлю ссылку на Легиум."
        sides = [side_msg(
            admin_id, data=invoice_admin_data(contractor, month, inv.amount),
            file=(pdf, filename),
            track={"type": SideMessageTrackType.ADMIN_REPLY,
                   "contractor_telegram": contractor.telegram or "",
                   "contractor_id": contractor.id},
        ) for admin_id in admin_ids]
        return respond([file_msg(pdf, filename, caption)], side_messages=sides)

    # ── Handlers: entry & menu ──

    def start(self, _payload: Payload, ctx: InteractContext) -> dict:
        if ctx.get("is_admin"):
            return respond([msg("Привет! Я бот для работы с контрагентами.\n\n"
                               "Список доступных комманд: /menu")], fsm_state=None)
        return self._greeting()

    def menu(self, _payload: Payload, ctx: InteractContext) -> dict:
        contractor, _ = self._get_contractor(ctx["user_id"])
        if contractor:
            return self._menu_response(contractor)
        return self._greeting()

    def free_text(self, payload: Payload, ctx: InteractContext) -> dict:
        contractor, contractors = self._get_contractor(ctx["user_id"])
        if contractor:
            return self._menu_response(contractor)
        query = payload.get("text", "").strip()
        matches = fuzzy_find(query, contractors, threshold=0.8)
        if matches:
            return self._suggest_duplicates(matches, query)
        return self._start_registration(query)

    def _suggest_duplicates(self, matches, query):
        buttons = [[{"text": self._dup_label(c), "data": f"dup:{c.id}"}] for c, _ in matches[:5]]
        buttons.append([{"text": "Я новый контрагент", "data": "dup:new"}])
        return respond(
            [msg("Похожие контрагенты уже есть в базе.\n"
                 "Если это вы — нажмите на соответствующую кнопку.", keyboard=buttons)],
            fsm_data={"alias": query},
        )

    def _start_registration(self, query):
        return respond(
            [msg("Не нашёл вас в базе. Давайте зарегистрируемся!"),
             self._type_selection_prompt()],
            fsm_state="waiting_type",
            fsm_data={"alias": query},
        )

    # ── Handlers: registration flow ──

    def type_selection(self, payload: Payload, ctx: InteractContext) -> dict:
        text = payload.get("text", "").strip().rstrip(".")
        ctype = self._TYPE_MAP.get(text.lower())
        if not ctype:
            return respond([msg("Пожалуйста, выберите 1, 2 или 3.")])
        alias = ctx.get("fsm_data", {}).get("alias", "")
        return respond(
            [msg(self._DATA_PROMPTS[ctype])], fsm_state="waiting_data",
            fsm_data={"contractor_type": ctype.value,
                      "collected_data": {"aliases": [alias]} if alias else {}},
        )

    def data_input(self, payload: Payload, ctx: InteractContext) -> dict:
        fsm_data = ctx.get("fsm_data", {})
        ctype = ContractorType(fsm_data["contractor_type"])
        raw_text = payload.get("text", "").strip()
        collected = fsm_data.get("collected_data", {})
        if ctx.get("progress"):
            ctx["progress"].emit("parse_data", "Обрабатываю данные")
        parsed = self._parse_input(raw_text, ctype, collected)
        if "parse_error" in parsed:
            return respond([msg("Не удалось обработать сообщение. Попробуйте отправить данные ещё раз.")])
        return self._process_parsed(parsed, collected, ctype, fsm_data, raw_text, ctx)

    def _parse_input(self, raw_text, ctype, collected):
        prev_warnings = validate_contractor_fields(collected, ctype) if collected else []
        return RegistrationParser().parse(raw_text, ctype, collected, prev_warnings or None)

    def _process_parsed(self, parsed, collected, ctype, fsm_data, raw_text, ctx):  # noqa: PLR0913
        llm_comment = parsed.pop("comment", None)
        validation_id = parsed.pop("_validation_id", None)
        self._merge_parsed(parsed, collected, validation_id)
        cls = CONTRACTOR_CLASS_BY_TYPE[ctype]
        _, missing = ContractorFactory().check_complete(collected, cls.required_fields())
        warnings = validate_contractor_fields(collected, ctype)
        if llm_comment:
            warnings.append(llm_comment)
        if missing or warnings:
            return self._registration_progress(cls, collected, missing, warnings, fsm_data)
        return self._complete_registration(collected, ctype, cls, raw_text, ctx)

    def _merge_parsed(self, parsed, collected, validation_id):
        for key, value in parsed.items():
            if isinstance(value, str) and value.strip():
                collected[key] = value.strip()
        if validation_id:
            collected["_validation_id"] = validation_id

    def _registration_progress(self, cls, collected, missing, warnings, fsm_data):
        filled = [
            {"label": label, "value": collected[field]}
            for field, label in cls.all_field_labels().items()
            if collected.get(field)
        ]
        return respond(
            [msg(data={"type": DT.REGISTRATION_PROGRESS, "filled": filled,
                       "missing": list(missing.values()) if missing else [],
                       "warnings": warnings})],
            fsm_data={**fsm_data, "collected_data": collected},
        )

    def _complete_registration(self, collected, ctype, cls, raw_text, ctx):
        self._maybe_add_russian_alias(collected, ctype)
        telegram_id = str(ctx["user_id"])
        contractors = load_all_contractors()
        contractor, secret_code = ContractorFactory().create(collected, ctype, telegram_id, contractors)
        sides = self._admin_registration_notify(collected, ctype, raw_text, ctx.get("admin_ids", []))
        messages = [self._registration_complete_msg(cls, collected, secret_code)]
        return self._try_invoice_after_registration(contractor, messages, sides)

    def _maybe_add_russian_alias(self, collected, ctype):
        if ctype != ContractorType.GLOBAL:
            return
        name_en = collected.get("name_en", "")
        if not name_en:
            return
        name_ru = RegistrationParser().translate_name(name_en)
        if name_ru:
            aliases = collected.get("aliases", [])
            if name_ru not in aliases:
                aliases.append(name_ru)
            collected["aliases"] = aliases

    def _admin_registration_notify(self, collected, ctype, raw_text, admin_ids):
        admin_data = {k: v for k, v in collected.items() if v and not k.startswith("_")}
        return [side_msg(admin_id, data={
            "type": DT.NEW_REGISTRATION, "contractor_type": ctype.value,
            "raw_text": raw_text, "parsed_data": admin_data,
        }) for admin_id in admin_ids]

    def _registration_complete_msg(self, cls, collected, secret_code):
        fields = [
            {"label": label, "value": collected.get(field, "")}
            for field, label in cls.all_field_labels().items()
            if collected.get(field)
        ]
        return msg(data={
            "type": DT.REGISTRATION_COMPLETE, "fields": fields,
            "aliases": collected.get("aliases", []),
            "secret_code": secret_code,
        })

    def _try_invoice_after_registration(self, contractor, messages, sides):
        month = prev_month()
        invoice_result = self._start_invoice_flow(contractor, month, {})
        if invoice_result:
            messages.extend(invoice_result["messages"])
            return respond(messages, side_messages=sides,
                          fsm_state=invoice_result.get("fsm_state"),
                          fsm_data=invoice_result.get("fsm_data"))
        messages.append(self._no_publications(month)["messages"][0])
        return respond(messages, side_messages=sides, fsm_state=None)

    # ── Handlers: verification ──

    def verification_code(self, payload: Payload, ctx: InteractContext) -> dict:
        fsm_data = ctx.get("fsm_data", {})
        contractor = find_contractor_by_id(fsm_data.get("pending_contractor_id"), load_all_contractors())
        if not contractor:
            return respond([msg("Контрагент не найден.")], fsm_state=None)
        code = payload.get("text", "").strip()
        if code.casefold() == contractor.secret_code.casefold():
            return self._bind_contractor(contractor, ctx)
        return self._verification_failed(fsm_data)

    def _bind_contractor(self, contractor, ctx):
        bind_telegram_id(contractor.id, ctx["user_id"])
        sides = [side_msg(admin_id,
                          text=f"Контрагент {contractor.display_name} привязался к Telegram.")
                 for admin_id in ctx.get("admin_ids", [])]
        return respond([
            msg(f"Отлично! Вы привязаны как {contractor.display_name}."),
            msg("Что хотите сделать?", keyboard=self._menu_keyboard(contractor)),
        ], side_messages=sides, fsm_state=None)

    def _verification_failed(self, fsm_data):
        attempts = fsm_data.get("verification_attempts", 0) + 1
        if attempts >= 3:
            return respond(
                [msg(f"Превышено количество попыток. Обратитесь к {ADMIN_TELEGRAM_TAG}.")],
                fsm_state=None)
        return respond(
            [msg(f"Неверный код. Осталось попыток: {3 - attempts}.")],
            fsm_data={**fsm_data, "verification_attempts": attempts})

    # ── Handlers: invoice & contract ──

    def sign_doc(self, _payload: Payload, ctx: InteractContext) -> dict:
        contractor, _ = self._get_contractor(ctx["user_id"])
        if not contractor:
            return self._greeting()
        month = prev_month()
        admin_ids = ctx.get("admin_ids", [])
        return (self._deliver_existing_invoice(contractor, month, admin_ids)
                or self._start_invoice_flow(contractor, month, {})
                or self._no_publications(month))

    def amount_input(self, payload: Payload, ctx: InteractContext) -> dict:
        fsm_data = ctx.get("fsm_data", {})
        contractor = find_contractor_by_id(fsm_data.get("invoice_contractor_id"), load_all_contractors())
        if not contractor:
            return respond([msg("Контрагент не найден.")], fsm_state=None)
        amount = self._parse_amount(payload.get("text", "").strip(),
                                    fsm_data.get("invoice_default_amount", 0))
        if isinstance(amount, dict):
            return amount
        return self._generate_contractor_invoice(contractor, fsm_data.get("invoice_month"), amount, ctx)

    def _parse_amount(self, text, default):
        if text.lower() in ("ок", "ok"):
            return Decimal(str(default))
        cleaned = re.sub(r"[^\d.]", "", text)
        if not cleaned:
            return respond([msg("Введите сумму числом или напишите «ок» для подтверждения.")])
        try:
            return Decimal(cleaned)
        except Exception:
            return respond([msg("Не удалось распознать сумму. Попробуйте ещё раз.")])

    def _generate_contractor_invoice(self, contractor, month, amount, ctx):
        if ctx.get("progress"):
            ctx["progress"].emit("generate_invoice", f"Генерирую документ для {contractor.display_name}")
        articles = RepublicGateway().fetch_articles(contractor, month)
        try:
            result = GenerateInvoice().create_and_save(contractor, month, amount, articles)
        except Exception as e:
            logger.exception("Generate failed for %s", contractor.display_name)
            return respond([msg(f"Ошибка генерации: {e}")], fsm_state=None)
        return self._format_contractor_invoice(result, contractor, month, ctx.get("admin_ids", []))

    def _format_contractor_invoice(self, result, contractor, month, admin_ids):
        invoice = result.invoice
        pdf = result.pdf_bytes
        filename = f"{contractor.display_name}+Unsigned.pdf"
        messages = [msg("Генерирую документ...")]
        if contractor.currency == Currency.EUR:
            messages.append(file_msg(pdf, filename,
                                     "Ваша проформа. Пожалуйста, подпишите и отправьте обратно в этот чат."))
            update_invoice_status(invoice.contractor_id, month, InvoiceStatus.SENT)
            return respond(messages, fsm_state=None)
        return self._format_rub_invoice(contractor, invoice, month, pdf, filename, messages, admin_ids)

    def _format_rub_invoice(self, contractor, invoice, month, pdf, filename, messages, admin_ids):  # noqa: PLR0913
        messages.append(file_msg(pdf, filename, "Ваш счёт-оферта. Скоро пришлю ссылку на Легиум."))
        sides = [side_msg(
            admin_id, data=invoice_admin_data(contractor, month, invoice.amount),
            file=(pdf, filename),
            track={"type": SideMessageTrackType.ADMIN_REPLY,
                   "contractor_telegram": contractor.telegram or "",
                   "contractor_id": contractor.id},
        ) for admin_id in admin_ids]
        return respond(messages, side_messages=sides, fsm_state=None)

    # ── Handlers: data updates ──

    def update_payment_data(self, _payload: Payload, ctx: InteractContext) -> dict:
        contractor, _ = self._get_contractor(ctx["user_id"])
        if not contractor:
            return self._greeting()
        return respond(
            [msg("Какие данные вы хотите обновить? Отправьте новые значения в свободной форме.\n\n"
                 "Отправьте «отмена» для отмены.")],
            fsm_state="waiting_update_data")

    def update_data(self, payload: Payload, ctx: InteractContext) -> dict:
        text = payload.get("text", "").strip()
        if text.lower() == "отмена":
            return respond([msg("Обновление отменено.")], fsm_state=None)
        contractor, _ = self._get_contractor(ctx["user_id"])
        if not contractor:
            return respond([msg("Контрагент не найден.")], fsm_state=None)
        return self._apply_data_update(text, contractor)

    def _apply_data_update(self, text, contractor):
        parsed = RegistrationParser().parse(text, contractor.type)
        if "parse_error" in parsed:
            return respond([msg("Не удалось обработать сообщение. Попробуйте ещё раз.")])
        updates = {k: v for k, v in parsed.items() if isinstance(v, str) and v.strip() and not k.startswith("_")}
        updates.pop("comment", None)
        if not updates:
            return respond([msg("Не удалось распознать изменения. Попробуйте ещё раз или отправьте «отмена».")])
        update_contractor_fields(contractor.id, updates)
        return respond([msg("Данные обновлены.")], fsm_state=None)

    # ── Handlers: editor sources ──

    def manage_redirects(self, _payload: Payload, ctx: InteractContext) -> dict:
        contractor, _ = self._get_contractor(ctx["user_id"])
        if not contractor or contractor.role_code != RoleCode.REDAKTOR:
            return self._greeting()
        return self._show_editor_sources(contractor)

    def editor_source_name(self, payload: Payload, ctx: InteractContext) -> dict:
        text = payload.get("text", "").strip()
        if text.lower() == "отмена":
            return respond([msg("Добавление отменено.")], fsm_state=None)
        contractor, _ = self._get_contractor(ctx["user_id"])
        if not contractor:
            return respond([msg("Контрагент не найден.")], fsm_state=None)
        return self._add_editor_source(text, contractor)

    def _add_editor_source(self, source_name, contractor):
        month = prev_month()
        add_redirect_rule(source_name, contractor.id)
        delete_invoice(contractor.id, month)
        redirect_in_budget(source_name, contractor, month)
        rules = find_redirect_rules_by_target(contractor.id)
        text, keyboard = self._editor_keyboard(rules)
        return respond([msg(f"Автор «{source_name}» добавлен."), msg(text, keyboard=keyboard)], fsm_state=None)

    def _remove_editor_source(self, source_name, contractor):
        month = prev_month()
        if remove_redirect_rule(source_name, contractor.id):
            delete_invoice(contractor.id, month)
            unredirect_in_budget(source_name, contractor, month)
        rules = find_redirect_rules_by_target(contractor.id)
        text, keyboard = self._editor_keyboard(rules)
        return respond([msg(text, keyboard=keyboard)])

    # ── Handlers: callbacks ──

    def dup_callback(self, payload: Payload, ctx: InteractContext) -> dict:
        callback_data = payload.get("callback_data", "")
        if callback_data == "dup:new":
            return respond([self._type_selection_prompt()], fsm_state="waiting_type")
        contractor_id = callback_data.removeprefix("dup:")
        contractor = find_contractor_by_id(contractor_id, load_all_contractors())
        if not contractor:
            return respond([msg("Контрагент не найден.")])
        return self._verify_or_reject(contractor, ctx["user_id"])

    def _verify_or_reject(self, contractor, user_id):
        if contractor.telegram and contractor.telegram != str(user_id):
            return respond([msg(
                f"{contractor.display_name} уже привязан к другому аккаунту Telegram. "
                f"Обратитесь к {ADMIN_TELEGRAM_TAG}, если это ошибка.")])
        return respond(
            [msg(f"✓ {contractor.display_name}"),
             msg(f"Введите секретный код для {contractor.display_name}. "
                 f"Если не знаете, обратитесь к {ADMIN_TELEGRAM_TAG}.")],
            fsm_state="waiting_verification",
            fsm_data={"pending_contractor_id": contractor.id, "verification_attempts": 0})

    def esrc_callback(self, payload: Payload, ctx: InteractContext) -> dict:
        data = payload.get("callback_data", "").removeprefix("esrc:")
        contractor, _ = self._get_contractor(ctx["user_id"])
        if not contractor:
            return respond([msg("Контрагент не найден.")])
        if data.startswith("rm:"):
            return self._remove_editor_source(data.removeprefix("rm:"), contractor)
        if data == "add":
            return respond([msg("Введите имя автора.\nОтправьте «отмена» для отмены.")],
                          fsm_state="waiting_editor_source_name")
        if data == "back":
            return respond([msg("Что хотите сделать?", keyboard=self._menu_keyboard(contractor))])
        return respond([msg("Неизвестное действие.")])

    def menu_callback(self, payload: Payload, ctx: InteractContext) -> dict:
        action = payload.get("callback_data", "").removeprefix("menu:")
        contractor, _ = self._get_contractor(ctx["user_id"])
        if not contractor:
            return respond([msg("Контрагент не найден.")])
        if action == "contract":
            return self.sign_doc(payload, ctx)
        if action == "update":
            return respond([msg("Какие данные вы хотите обновить? Отправьте новые значения в свободной форме.\n\n"
                               "Отправьте «отмена» для отмены.")], fsm_state="waiting_update_data")
        if action == "editor":
            return self._show_editor_sources(contractor)
        return respond([msg("Неизвестное действие.")])

    # ── Handlers: documents ──

    def document(self, payload: Payload, ctx: InteractContext) -> dict:
        user_id = ctx["user_id"]
        contractor, _ = self._get_contractor(user_id)
        sender_info = contractor.display_name if contractor else f"TG#{user_id}"
        drive_link = self._handle_pdf_upload(contractor, payload, ctx.get("progress"))
        if isinstance(drive_link, dict):
            return drive_link
        admin_ids = ctx.get("admin_ids", [])
        sides = [side_msg(aid, data={"type": DT.DOCUMENT_RECEIVED, "sender": sender_info,
                                     "drive_link": drive_link})
                 for aid in admin_ids if aid != user_id]
        return respond([msg("Спасибо! Документ получен.")], side_messages=sides)

    def _handle_pdf_upload(self, contractor, payload, progress):
        if not isinstance(contractor, GlobalContractor) or not payload.get("file_b64"):
            return None
        if not payload.get("mime", "").endswith("/pdf"):
            return respond([msg("Пожалуйста, отправьте подписанный документ в формате PDF.\n\n"
                               f"Если возникли вопросы — напишите {ADMIN_TELEGRAM_TAG}.")])
        return self._upload_signed_pdf(contractor, payload, progress)

    def _upload_signed_pdf(self, contractor, payload, progress):
        content = base64.b64decode(payload["file_b64"])
        month = prev_month()
        if progress:
            progress.emit("upload_drive", "Загружаю документ на Google Drive")
        link = DriveGateway().upload_invoice_pdf(contractor, month, payload.get("filename", "document"), content)
        update_invoice_status(contractor.id, month, InvoiceStatus.SIGNED)
        return link

    def non_document(self, _payload: Payload, ctx: InteractContext) -> dict:
        if ctx.get("fsm_state") is not None:
            return respond([msg("Пожалуйста, отправьте текстовое сообщение.")])
        contractor, _ = self._get_contractor(ctx["user_id"])
        if isinstance(contractor, GlobalContractor):
            return respond([msg(
                "Мы ожидаем от вас подписанный PDF-документ. "
                "Пожалуйста, отправьте его в этот чат.\n\n"
                f"Если возникли вопросы — напишите {ADMIN_TELEGRAM_TAG}.")])
        return respond([])
