"""Centralized bot reply strings, grouped by flow context.

Each class mirrors a flow or domain area. Plain strings for static replies,
.format()-style templates for dynamic ones.

Usage in handlers:
    from telegram_bot import replies
    await message.answer(replies.lookup.not_found)
    await message.answer(replies.invoice.proforma_caption)
    await message.answer(replies.verification.no_articles.format(month=month))
"""

from common.config import ADMIN_TELEGRAM_TAG, PRODUCT_NAME
from common.models import ContractorType


# ── /start ───────────────────────────────────────────────────────────

class start:
    admin = (
        "Привет! Я бот для работы с контрагентами.\n\n"
        "Команды администратора:\n"
        "/generate <имя> — сгенерировать документ\n"
        "/generate_invoices — сгенерировать все счета\n"
        "/send_global_invoices — отправить глобальные счета\n"
        "/budget — расчёт бюджета\n"
        "/upload_to_airtable — загрузить банковскую выписку\n"
        "Или отправьте имя контрагента для поиска."
    )
    contractor = (
        "Здравствуйте! Я бот для оформления оплаты.\n\n"
        f"Под каким именем/псевдонимом вы работаете на {PRODUCT_NAME}?"
    )


# ── Contractor lookup ────────────────────────────────────────────────

class lookup:
    not_found = "Контрагент не найден."
    no_invoices = "Здравствуйте, {name}! На данный момент нет счетов за {month}."
    fuzzy_match = (
        "Похожие контрагенты уже есть в базе.\n"
        "Если это вы — нажмите на соответствующую кнопку."
    )
    fuzzy_suggestions = "Точного совпадения нет. Возможные варианты:\n{suggestions}"


# ── Registration ─────────────────────────────────────────────────────

class registration:
    begin = "Не нашёл вас в базе. Давайте зарегистрируемся!"
    type_prompt = (
        "Какой у вас статус?\n\n"
        "1. Самозанятый (хочу получать в рублях)\n"
        "2. ИП (хочу получать в рублях)\n"
        "3. Зарубежный контрагент (хочу получать в евро)\n\n"
        "Отправьте цифру (1, 2 или 3)."
    )
    type_invalid = "Пожалуйста, выберите 1, 2 или 3."
    data_prompts = {
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
    parse_error = "Не удалось обработать сообщение. Попробуйте отправить данные ещё раз."
    no_articles = (
        "Публикаций за {month} не найдено.\n"
        f"Если это ошибка — напишите {ADMIN_TELEGRAM_TAG}."
    )


# ── Verification ─────────────────────────────────────────────────────

class verification:
    code_prompt = (
        "Введите секретный код для {name}. "
        f"Если не знаете, обратитесь к {ADMIN_TELEGRAM_TAG}."
    )
    success = "Отлично! Вы привязаны как {name}."
    wrong_code = "Неверный код. Осталось попыток: {remaining}"
    too_many_attempts = f"Превышено количество попыток. Обратитесь к {ADMIN_TELEGRAM_TAG}."
    already_bound = (
        "{name} уже привязан к другому аккаунту Telegram. "
        f"Обратитесь к {ADMIN_TELEGRAM_TAG}, если это ошибка."
    )


# ── Invoice (amount input + delivery) ────────────────────────────────

class invoice:
    amount_prompt = (
        "У вас {pub_word} за {month}.\n"
        "{explanation}\n\n"
        "Отправьте иную сумму или напишите ок для подтверждения."
    )
    amount_invalid = "Введите сумму числом или напишите ок для подтверждения."
    amount_parse_error = "Не удалось распознать сумму. Попробуйте ещё раз."
    generating = "Генерирую документ..."
    generating_for = "Генерирую документ для {name}..."
    generation_error = "Ошибка генерации: {error}"
    proforma_caption = "Ваша проформа. Пожалуйста, подпишите и отправьте обратно в этот чат."
    rub_invoice_caption = "Ваш счёт-оферта. Скоро пришлю ссылку на Легиум."
    proforma_already_sent = "Ваша проформа уже отправлена, проверьте историю чата."
    legium_already_sent = "Ссылка на Легиум уже отправлена, проверьте историю чата."
    legium_link = (
        "Ссылка на Легиум:\n\n{url}\n\n"
        "Перейдите по ссылке и подпишите. После этого ничего дополнительного делать не нужно."
    )
    legium_sent = "Ссылка отправлена контрагенту."
    legium_send_error = "Не удалось отправить: {error}"
    legium_admin_caption = (
        "{name} ({type}) — {month}\n"
        "Сумма: {amount} ₽\n\n"
        "Ответьте на это сообщение ссылкой из Легиума."
    )
    no_articles = "У {name} нет публикаций за {month}."


# ── Document upload ──────────────────────────────────────────────────

class document:
    received = "Спасибо! Документ получен."
    pdf_reminder = (
        "Мы ожидаем от вас подписанный PDF-документ. "
        "Пожалуйста, отправьте его в этот чат.\n\n"
        f"Если возникли вопросы — напишите {ADMIN_TELEGRAM_TAG}."
    )
    pdf_required = (
        "Пожалуйста, отправьте подписанный документ в формате PDF.\n\n"
        f"Если возникли вопросы — напишите {ADMIN_TELEGRAM_TAG}."
    )


# ── Admin commands ───────────────────────────────────────────────────

class admin:
    generate_usage = "Использование: /generate <имя контрагента>"
    proforma_ready = "Проформа готова. Отправьте контрагенту на подпись."
    invoice_ready = "Счёт-оферта готова. Ожидайте ссылки на легиум."
    budget_generating = "Генерирую бюджетную таблицу за {month}..."
    budget_done = "Таблица готова: {url}"
    budget_error = "Ошибка при создании таблицы: {error}"
    no_draft_global = "Нет неотправленных глобальных счетов за {month}."
    upload_usage = "Прикрепите CSV-файл банковской выписки с подписью:\n/upload_to_airtable <курс AED→RUB>"
    upload_processing = "Обрабатываю выписку (курс {rate} AED→RUB)..."
    upload_done = "Загружено {count} записей в Airtable."
    upload_error = "Ошибка загрузки: {error}"
