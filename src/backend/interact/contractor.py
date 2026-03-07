"""Contractor interaction handlers — registration, verification, invoicing, editor sources."""

import base64
import logging
import re
from decimal import Decimal

from backend import (
    add_redirect_rule, bind_telegram_id, create_and_save_invoice,
    delete_invoice, fetch_articles, find_contractor_by_id,
    find_contractor_by_telegram_id, find_redirect_rules_by_target,
    fuzzy_find, load_all_contractors, redirect_in_budget,
    remove_redirect_rule, unredirect_in_budget, update_contractor_fields,
    update_invoice_status, upload_invoice_pdf, validate_contractor_fields,
)
from backend.commands.contractor.create import check_registration_complete, create_contractor
from backend.commands.contractor.registration import parse_registration_data, translate_contractor_name
from backend.commands.invoice.service import DeliveryAction, prepare_new_invoice_data, resolve_existing_invoice
from backend.config import ADMIN_TELEGRAM_TAG, PRODUCT_NAME
from backend.models import (
    CONTRACTOR_CLASS_BY_TYPE, Contractor, ContractorType, Currency,
    GlobalContractor, InvoiceStatus, RoleCode,
)
from backend.interact.helpers import (
    msg, file_msg, side_msg, respond,
    prev_month, invoice_admin_data, ROLE_LABELS,
)

logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────


def _linked_menu_keyboard(contractor: Contractor) -> list:
    rows = [
        [{"text": "Подписать договор для выплат", "data": "menu:contract"}],
        [{"text": "Обновить мои платежные данные", "data": "menu:update"}],
    ]
    if contractor.role_code == RoleCode.REDAKTOR:
        rows.append([{"text": "Настроить, за кого я получаю деньги", "data": "menu:editor"}])
    return rows


def _dup_label(c: Contractor) -> str:
    alias = c.aliases[0] if c.aliases else ""
    real = c.display_name
    return f"{alias} ({real})" if alias and alias != real else real


def _get_contractor(user_id: int):
    contractors = load_all_contractors()
    return find_contractor_by_telegram_id(user_id, contractors), contractors


_DATA_PROMPTS = {
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

def _editor_sources_keyboard(rules) -> tuple[str, list]:
    rows = []
    if rules:
        text = "Сейчас вы получаете деньги за:\n"
        for r in rules:
            text += f"\n  - {r.source_name}"
            rows.append([{"text": f"❌ {r.source_name}", "data": f"esrc:rm:{r.source_name}"}])
    else:
        text = "У вас пока нет привязанных авторов."
    rows.append([{"text": "Добавить автора", "data": "esrc:add"}])
    rows.append([{"text": "← Назад", "data": "esrc:back"}])
    return text, rows


def _start_invoice_flow(contractor, month, fsm_data: dict) -> dict | None:
    """Try to start invoice flow. Returns partial response or None."""
    data = prepare_new_invoice_data(contractor, month)
    if not data:
        return None
    new_data = {
        **fsm_data,
        "invoice_contractor_id": contractor.id,
        "invoice_month": month,
        "invoice_article_ids": data.article_ids,
        "invoice_default_amount": data.default_amount,
    }
    return respond(
        [msg(data={
            "type": "invoice_prompt",
            "pub_word": data.pub_word,
            "month": month,
            "explanation": data.explanation,
            "default_amount": data.default_amount,
        })],
        fsm_state="waiting_amount",
        fsm_data=new_data,
    )


def _deliver_existing_invoice(contractor, month, admin_ids) -> dict | None:
    """Check for pre-generated invoice. Returns response dict or None."""
    result = resolve_existing_invoice(contractor, month)
    if not result:
        return None

    inv = result.prepared.invoice
    pdf_bytes = result.prepared.pdf_bytes
    filename = f"{contractor.display_name}+Unsigned.pdf"
    action = result.action

    if action == DeliveryAction.SEND_PROFORMA:
        update_invoice_status(inv.contractor_id, month, InvoiceStatus.SENT)
        return respond([file_msg(pdf_bytes, filename,
            "Ваша проформа. Пожалуйста, подпишите и отправьте обратно в этот чат.")])

    if action == DeliveryAction.PROFORMA_ALREADY_SENT:
        return respond([msg("Ваша проформа уже отправлена, проверьте историю чата.")])

    if action == DeliveryAction.SEND_RUB_WITH_LEGIUM:
        if inv.status == InvoiceStatus.DRAFT:
            update_invoice_status(inv.contractor_id, month, InvoiceStatus.SENT)
        return respond([file_msg(pdf_bytes, filename,
            f"Ссылка на Легиум:\n\n{inv.legium_link}\n\n"
            f"Перейдите по ссылке и подпишите. "
            f"Если в документе есть ошибка — напишите {ADMIN_TELEGRAM_TAG}.")])

    if action == DeliveryAction.SEND_RUB_DRAFT:
        caption = "Ваш счёт-оферта. Скоро пришлю ссылку на Легиум."
        sides = []
        for admin_id in admin_ids:
            sides.append(side_msg(
                admin_id,
                data=invoice_admin_data(contractor, month, inv.amount),
                pdf_bytes=pdf_bytes, filename=filename,
                track={"type": "admin_reply",
                       "contractor_telegram": contractor.telegram or "",
                       "contractor_id": contractor.id},
            ))
        return respond([file_msg(pdf_bytes, filename, caption)], side_messages=sides)

    if action == DeliveryAction.RUB_ALREADY_SENT:
        return respond([msg("Ссылка на Легиум уже отправлена, проверьте историю чата.")])

    return None


# ── Handlers ─────────────────────────────────────────────────────────

def handle_start(payload: dict, ctx: dict) -> dict:
    if ctx.get("is_admin"):
        return respond([msg(
            "Привет! Я бот для работы с контрагентами.\n\n"
            "Список доступных комманд: /menu"
        )], fsm_state=None)
    return respond([msg(
        "Здравствуйте! Я бот для оформления оплаты.\n\n"
        f"Под каким именем/псевдонимом вы работаете на {PRODUCT_NAME}?"
    )], fsm_state=None)


def handle_menu(payload: dict, ctx: dict) -> dict:
    contractor, _ = _get_contractor(ctx["user_id"])
    if contractor:
        return respond(
            [msg("Что хотите сделать?", keyboard=_linked_menu_keyboard(contractor))],
            fsm_state=None,
        )
    return respond([msg(
        "Здравствуйте! Я бот для оформления оплаты.\n\n"
        f"Под каким именем/псевдонимом вы работаете на {PRODUCT_NAME}?"
    )], fsm_state=None)


def handle_free_text(payload: dict, ctx: dict) -> dict:
    user_id = ctx["user_id"]
    contractors = load_all_contractors()
    contractor = find_contractor_by_telegram_id(user_id, contractors)
    if contractor:
        return respond(
            [msg("Что хотите сделать?", keyboard=_linked_menu_keyboard(contractor))],
            fsm_state=None,
        )

    query = payload.get("text", "").strip()
    matches = fuzzy_find(query, contractors, threshold=0.8)
    if matches:
        buttons = [[{"text": _dup_label(c), "data": f"dup:{c.id}"}] for c, _ in matches[:5]]
        buttons.append([{"text": "Я новый контрагент", "data": "dup:new"}])
        return respond(
            [msg("Похожие контрагенты уже есть в базе.\n"
                 "Если это вы — нажмите на соответствующую кнопку.", keyboard=buttons)],
            fsm_data={"alias": query},
        )

    return respond(
        [msg("Не нашёл вас в базе. Давайте зарегистрируемся!"),
         msg("Какой у вас статус?\n\n"
             "1. Самозанятый (хочу получать в рублях)\n"
             "2. ИП (хочу получать в рублях)\n"
             "3. Зарубежный контрагент (хочу получать в евро)\n\n"
             "Отправьте цифру (1, 2 или 3).")],
        fsm_state="waiting_type",
        fsm_data={"alias": query},
    )


def handle_type_selection(payload: dict, ctx: dict) -> dict:
    text = payload.get("text", "").strip().rstrip(".")
    type_map = {
        "1": ContractorType.SAMOZANYATY, "2": ContractorType.IP, "3": ContractorType.GLOBAL,
        "самозанятый": ContractorType.SAMOZANYATY, "ип": ContractorType.IP, "global": ContractorType.GLOBAL,
    }
    ctype = type_map.get(text.lower())
    if not ctype:
        return respond([msg("Пожалуйста, выберите 1, 2 или 3.")])

    alias = ctx.get("fsm_data", {}).get("alias", "")
    return respond(
        [msg(_DATA_PROMPTS[ctype])],
        fsm_state="waiting_data",
        fsm_data={
            "contractor_type": ctype.value,
            "collected_data": {"aliases": [alias]} if alias else {},
        },
    )


def handle_data_input(payload: dict, ctx: dict) -> dict:
    fsm_data = ctx.get("fsm_data", {})
    ctype = ContractorType(fsm_data["contractor_type"])
    raw_text = payload.get("text", "").strip()
    collected = fsm_data.get("collected_data", {})
    cls = CONTRACTOR_CLASS_BY_TYPE[ctype]

    prev_warnings = validate_contractor_fields(collected, ctype) if collected else []
    parsed = parse_registration_data(raw_text, ctype, collected, prev_warnings or None)
    if "parse_error" in parsed:
        return respond([msg("Не удалось обработать сообщение. Попробуйте отправить данные ещё раз.")])

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
        filled = [
            {"label": label, "value": collected[field]}
            for field, label in all_fields.items()
            if collected.get(field)
        ]
        return respond(
            [msg(data={
                "type": "registration_progress",
                "filled": filled,
                "missing": list(missing.values()) if missing else [],
                "warnings": warnings,
            })],
            fsm_data={**fsm_data, "collected_data": collected},
        )

    # For Global contractors, translate name and add as alias
    if ctype == ContractorType.GLOBAL:
        name_en = collected.get("name_en", "")
        if name_en:
            name_ru = translate_contractor_name(name_en)
            if name_ru:
                aliases = collected.get("aliases", [])
                if name_ru not in aliases:
                    aliases.append(name_ru)
                collected["aliases"] = aliases

    # Registration complete — save and start invoice flow
    return _finish_registration(collected, ctype, cls, raw_text, ctx)


def _finish_registration(collected: dict, ctype: ContractorType, cls: type,
                         raw_text: str, ctx: dict) -> dict:
    all_labels = cls.all_field_labels()
    fields = [
        {"label": label, "value": collected.get(field, "")}
        for field, label in all_labels.items()
        if collected.get(field)
    ]
    aliases = collected.get("aliases", [])

    telegram_id = str(ctx["user_id"])
    contractors = load_all_contractors()
    contractor, secret_code = create_contractor(collected, ctype, telegram_id, contractors)

    # Notify admins
    admin_ids = ctx.get("admin_ids", [])
    sides = []
    admin_data = {k: v for k, v in collected.items() if v and not k.startswith("_")}
    for admin_id in admin_ids:
        sides.append(side_msg(admin_id, data={
            "type": "new_registration",
            "contractor_type": ctype.value,
            "raw_text": raw_text,
            "parsed_data": admin_data,
        }))

    messages = [msg(data={
        "type": "registration_complete",
        "fields": fields,
        "aliases": aliases,
        "secret_code": secret_code,
    })]

    if not contractor:
        return respond(messages, side_messages=sides, fsm_state=None)

    # Try starting invoice flow
    month = prev_month()
    invoice_result = _start_invoice_flow(contractor, month, {})
    if invoice_result:
        messages.extend(invoice_result["messages"])
        return respond(
            messages, side_messages=sides,
            fsm_state=invoice_result.get("fsm_state"),
            fsm_data=invoice_result.get("fsm_data"),
        )

    messages.append(msg(
        f"Публикаций за {month} не найдено.\n"
        f"Если это ошибка — напишите {ADMIN_TELEGRAM_TAG}."
    ))
    return respond(messages, side_messages=sides, fsm_state=None)


def handle_verification_code(payload: dict, ctx: dict) -> dict:
    fsm_data = ctx.get("fsm_data", {})
    contractor_id = fsm_data.get("pending_contractor_id")
    attempts = fsm_data.get("verification_attempts", 0)

    contractor = find_contractor_by_id(contractor_id, load_all_contractors())
    if not contractor:
        return respond([msg("Контрагент не найден.")], fsm_state=None)

    code = payload.get("text", "").strip()
    if code.casefold() == contractor.secret_code.casefold():
        user_id = ctx["user_id"]
        bind_telegram_id(contractor.id, user_id)

        sides = []
        for admin_id in ctx.get("admin_ids", []):
            sides.append(side_msg(admin_id,
                f"Контрагент {contractor.display_name} привязался к Telegram."))

        messages = [
            msg(f"Отлично! Вы привязаны как {contractor.display_name}."),
            msg("Что хотите сделать?", keyboard=_linked_menu_keyboard(contractor)),
        ]
        return respond(messages, side_messages=sides, fsm_state=None)

    attempts += 1
    if attempts >= 3:
        return respond(
            [msg(f"Превышено количество попыток. Обратитесь к {ADMIN_TELEGRAM_TAG}.")],
            fsm_state=None,
        )

    remaining = 3 - attempts
    return respond(
        [msg(f"Неверный код. Осталось попыток: {remaining}.")],
        fsm_data={**fsm_data, "verification_attempts": attempts},
    )


def handle_sign_doc(payload: dict, ctx: dict) -> dict:
    contractor, _ = _get_contractor(ctx["user_id"])
    if not contractor:
        return respond([msg(
            "Здравствуйте! Я бот для оформления оплаты.\n\n"
            f"Под каким именем/псевдонимом вы работаете на {PRODUCT_NAME}?"
        )])

    month = prev_month()
    admin_ids = ctx.get("admin_ids", [])

    # Try delivering existing invoice
    delivery = _deliver_existing_invoice(contractor, month, admin_ids)
    if delivery:
        return delivery

    # Try starting invoice flow
    invoice = _start_invoice_flow(contractor, month, {})
    if invoice:
        return invoice

    return respond([msg(
        f"Публикаций за {month} не найдено.\n"
        f"Если это ошибка — напишите {ADMIN_TELEGRAM_TAG}."
    )])


def handle_update_payment_data(payload: dict, ctx: dict) -> dict:
    contractor, _ = _get_contractor(ctx["user_id"])
    if not contractor:
        return respond([msg(
            "Здравствуйте! Я бот для оформления оплаты.\n\n"
            f"Под каким именем/псевдонимом вы работаете на {PRODUCT_NAME}?"
        )])
    return respond(
        [msg("Какие данные вы хотите обновить? Отправьте новые значения в свободной форме.\n\n"
             "Отправьте «отмена» для отмены.")],
        fsm_state="waiting_update_data",
    )


def handle_manage_redirects(payload: dict, ctx: dict) -> dict:
    contractor, _ = _get_contractor(ctx["user_id"])
    if not contractor or contractor.role_code != RoleCode.REDAKTOR:
        return respond([msg(
            "Здравствуйте! Я бот для оформления оплаты.\n\n"
            f"Под каким именем/псевдонимом вы работаете на {PRODUCT_NAME}?"
        )])
    rules = find_redirect_rules_by_target(contractor.id)
    text, keyboard = _editor_sources_keyboard(rules)
    return respond([msg(text, keyboard=keyboard)])


def handle_amount_input(payload: dict, ctx: dict) -> dict:
    fsm_data = ctx.get("fsm_data", {})
    contractor_id = fsm_data.get("invoice_contractor_id")
    month = fsm_data.get("invoice_month")
    default_amount = fsm_data.get("invoice_default_amount", 0)

    contractor = find_contractor_by_id(contractor_id, load_all_contractors())
    if not contractor:
        return respond([msg("Контрагент не найден.")], fsm_state=None)

    text = payload.get("text", "").strip()
    if text.lower() in ("ок", "ok"):
        amount = Decimal(str(default_amount))
    else:
        cleaned = re.sub(r"[^\d.]", "", text)
        if not cleaned:
            return respond([msg("Введите сумму числом или напишите «ок» для подтверждения.")])
        try:
            amount = Decimal(cleaned)
        except Exception:
            return respond([msg("Не удалось распознать сумму. Попробуйте ещё раз.")])

    articles = fetch_articles(contractor, month)

    try:
        result = create_and_save_invoice(contractor, month, amount, articles)
    except Exception as e:
        logger.exception("Generate failed for %s", contractor.display_name)
        return respond([msg(f"Ошибка генерации: {e}")], fsm_state=None)

    invoice = result.invoice
    pdf_bytes = result.pdf_bytes
    filename = f"{contractor.display_name}+Unsigned.pdf"

    messages = [msg("Генерирую документ...")]
    sides = []

    if contractor.currency == Currency.EUR:
        messages.append(file_msg(pdf_bytes, filename,
            "Ваша проформа. Пожалуйста, подпишите и отправьте обратно в этот чат."))
        update_invoice_status(invoice.contractor_id, month, InvoiceStatus.SENT)
    else:
        messages.append(file_msg(pdf_bytes, filename,
            "Ваш счёт-оферта. Скоро пришлю ссылку на Легиум."))
        for admin_id in ctx.get("admin_ids", []):
            sides.append(side_msg(
                admin_id,
                data=invoice_admin_data(contractor, month, invoice.amount),
                pdf_bytes=pdf_bytes, filename=filename,
                track={"type": "admin_reply",
                       "contractor_telegram": contractor.telegram or "",
                       "contractor_id": contractor.id},
            ))

    return respond(messages, side_messages=sides, fsm_state=None)


def handle_update_data(payload: dict, ctx: dict) -> dict:
    text = payload.get("text", "").strip()
    if text.lower() == "отмена":
        return respond([msg("Обновление отменено.")], fsm_state=None)

    contractor, _ = _get_contractor(ctx["user_id"])
    if not contractor:
        return respond([msg("Контрагент не найден.")], fsm_state=None)

    parsed = parse_registration_data(text, contractor.type)
    if "parse_error" in parsed:
        return respond([msg("Не удалось обработать сообщение. Попробуйте ещё раз.")])

    updates = {k: v for k, v in parsed.items() if isinstance(v, str) and v.strip() and not k.startswith("_")}
    updates.pop("comment", None)

    if not updates:
        return respond([msg("Не удалось распознать изменения. Попробуйте ещё раз или отправьте «отмена».")])

    update_contractor_fields(contractor.id, updates)
    return respond([msg("Данные обновлены.")], fsm_state=None)


def handle_editor_source_name(payload: dict, ctx: dict) -> dict:
    text = payload.get("text", "").strip()
    if text.lower() == "отмена":
        return respond([msg("Добавление отменено.")], fsm_state=None)

    contractor, _ = _get_contractor(ctx["user_id"])
    if not contractor:
        return respond([msg("Контрагент не найден.")], fsm_state=None)

    month = prev_month()
    add_redirect_rule(text, contractor.id)
    delete_invoice(contractor.id, month)
    redirect_in_budget(text, contractor, month)

    rules = find_redirect_rules_by_target(contractor.id)
    text_out, keyboard = _editor_sources_keyboard(rules)
    return respond(
        [msg(f"Автор «{text}» добавлен."), msg(text_out, keyboard=keyboard)],
        fsm_state=None,
    )


def handle_dup_callback(payload: dict, ctx: dict) -> dict:
    callback_data = payload.get("callback_data", "")

    if callback_data == "dup:new":
        return respond(
            [msg("Какой у вас статус?\n\n"
                 "1. Самозанятый (хочу получать в рублях)\n"
                 "2. ИП (хочу получать в рублях)\n"
                 "3. Зарубежный контрагент (хочу получать в евро)\n\n"
                 "Отправьте цифру (1, 2 или 3).")],
            fsm_state="waiting_type",
        )

    contractor_id = callback_data.removeprefix("dup:")
    contractor = find_contractor_by_id(contractor_id, load_all_contractors())
    if not contractor:
        return respond([msg("Контрагент не найден.")])

    user_id = ctx["user_id"]

    if contractor.telegram and contractor.telegram != str(user_id):
        return respond([msg(
            f"{contractor.display_name} уже привязан к другому аккаунту Telegram. "
            f"Обратитесь к {ADMIN_TELEGRAM_TAG}, если это ошибка."
        )])

    return respond(
        [msg(f"✓ {contractor.display_name}"),
         msg(f"Введите секретный код для {contractor.display_name}. "
             f"Если не знаете, обратитесь к {ADMIN_TELEGRAM_TAG}.")],
        fsm_state="waiting_verification",
        fsm_data={"pending_contractor_id": contractor.id, "verification_attempts": 0},
    )


def handle_esrc_callback(payload: dict, ctx: dict) -> dict:
    callback_data = payload.get("callback_data", "")
    data = callback_data.removeprefix("esrc:")

    contractor, _ = _get_contractor(ctx["user_id"])
    if not contractor:
        return respond([msg("Контрагент не найден.")])

    if data.startswith("rm:"):
        source_name = data.removeprefix("rm:")
        month = prev_month()
        removed = remove_redirect_rule(source_name, contractor.id)
        if removed:
            delete_invoice(contractor.id, month)
            unredirect_in_budget(source_name, contractor, month)
        rules = find_redirect_rules_by_target(contractor.id)
        text, keyboard = _editor_sources_keyboard(rules)
        return respond([msg(text, keyboard=keyboard)])

    if data == "add":
        return respond(
            [msg("Введите имя автора.\nОтправьте «отмена» для отмены.")],
            fsm_state="waiting_editor_source_name",
        )

    if data == "back":
        return respond([msg("Что хотите сделать?", keyboard=_linked_menu_keyboard(contractor))])

    return respond([msg("Неизвестное действие.")])


def handle_menu_callback(payload: dict, ctx: dict) -> dict:
    callback_data = payload.get("callback_data", "")
    action = callback_data.removeprefix("menu:")

    contractor, _ = _get_contractor(ctx["user_id"])
    if not contractor:
        return respond([msg("Контрагент не найден.")])

    if action == "contract":
        return handle_sign_doc(payload, ctx)
    if action == "update":
        return respond(
            [msg("Какие данные вы хотите обновить? Отправьте новые значения в свободной форме.\n\n"
                 "Отправьте «отмена» для отмены.")],
            fsm_state="waiting_update_data",
        )
    if action == "editor":
        rules = find_redirect_rules_by_target(contractor.id)
        text, keyboard = _editor_sources_keyboard(rules)
        return respond([msg(text, keyboard=keyboard)])

    return respond([msg("Неизвестное действие.")])


def handle_document(payload: dict, ctx: dict) -> dict:
    user_id = ctx["user_id"]
    admin_ids = ctx.get("admin_ids", [])
    contractor, _ = _get_contractor(user_id)
    sender_info = contractor.display_name if contractor else f"TG#{user_id}"

    file_b64 = payload.get("file_b64")
    filename = payload.get("filename", "document")
    mime = payload.get("mime", "")

    drive_link = None
    if isinstance(contractor, GlobalContractor) and file_b64:
        if not mime.endswith("/pdf"):
            return respond([msg(
                "Пожалуйста, отправьте подписанный документ в формате PDF.\n\n"
                f"Если возникли вопросы — напишите {ADMIN_TELEGRAM_TAG}."
            )])
        try:
            content = base64.b64decode(file_b64)
            month = prev_month()
            drive_link = upload_invoice_pdf(contractor, month, filename, content)
            update_invoice_status(contractor.id, month, InvoiceStatus.SIGNED)
        except Exception as e:
            logger.error("Failed to upload signed doc to Drive: %s", e)

    sides = []
    for admin_id in admin_ids:
        if admin_id != user_id:
            sides.append(side_msg(admin_id, data={
                "type": "document_received",
                "sender": sender_info,
                "drive_link": drive_link,
            }))

    return respond(
        [msg("Спасибо! Документ получен.")],
        side_messages=sides,
    )


def handle_non_document(payload: dict, ctx: dict) -> dict:
    fsm_state = ctx.get("fsm_state")
    if fsm_state is not None:
        return respond([msg("Пожалуйста, отправьте текстовое сообщение.")])

    contractor, _ = _get_contractor(ctx["user_id"])
    if isinstance(contractor, GlobalContractor):
        return respond([msg(
            "Мы ожидаем от вас подписанный PDF-документ. "
            "Пожалуйста, отправьте его в этот чат.\n\n"
            f"Если возникли вопросы — напишите {ADMIN_TELEGRAM_TAG}."
        )])
    return respond([])
