"""Generic renderer — converts backend interact responses into Telegram messages."""

import base64
import logging

from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from telegram_bot.bot_helpers import bot
from telegram_bot.handler_utils import _admin_reply_map, _send

logger = logging.getLogger(__name__)


# ── Structured data formatters ───────────────────────────────────────

def _fmt_contractor_info(d: dict) -> str:
    lines = [d["name"]]
    lines.append(f"Тип: {d['contractor_type']}")
    lines.append(f"Роль: {d['role']}")
    if d.get("mags"):
        lines.append(f"Издания: {d['mags']}")
    if d.get("email"):
        lines.append(f"Email: {d['email']}")
    lines.append(f"Telegram: {'привязан' if d.get('telegram_linked') else 'не привязан'}")
    lines.append(f"Номер счёта: {d.get('invoice_number', '')}")
    lines.append(f"Банковские данные: {'заполнены' if d.get('has_bank_data') else 'не заполнены'}")
    return "\n".join(lines)


def _fmt_articles_list(d: dict) -> str:
    ids_list = "\n".join(f"  - {a}" for a in d["article_ids"])
    return (f"{d['name']} ({d['role']})\n"
            f"Месяц: {d['month']}\n"
            f"Статей: {d['count']}\n\n"
            f"{ids_list}")


def _fmt_operation_summary(d: dict) -> str:
    parts = [d["header"]]
    counts = d.get("counts")
    if counts:
        total = d.get("total_generated", 0)
        if total:
            parts.append(
                f"Сгенерировано: {counts['global']} global, "
                f"{counts['samozanyaty']} самозанятых, {counts['ip']} ИП"
            )
        else:
            parts.append("Новых счетов не сгенерировано.")
    errors = d.get("errors")
    if errors:
        parts.append("Ошибки:\n" + "\n".join(f"  - {e}" for e in errors))
    return "\n\n".join(parts)


def _fmt_orphan_list(d: dict) -> str:
    lines = "\n".join(f"  - {n}" for n in d["orphans"])
    return f"В бюджете за {d['month']}, но нет привязанного контрагента ({len(d['orphans'])}):\n{lines}"


def _fmt_fuzzy_suggestions(d: dict) -> str:
    suggestions = "\n".join(f"  - {s['name']} ({s['type']})" for s in d["matches"])
    return f"Точного совпадения нет. Возможные варианты:\n{suggestions}"


def _fmt_registration_progress(d: dict) -> str:
    filled_lines = "\n".join(f"  ✓ {f['label']}: {f['value']}" for f in d["filled"])
    parts = [f"Вот что я уже получил:\n{filled_lines}"]
    if d.get("missing"):
        parts.append(f"Ещё нужно: {', '.join(d['missing'])}.")
    if d.get("warnings"):
        parts.append("\n".join(f"  ⚠ {w}" for w in d["warnings"]))
    parts.append("Пришлите исправленные/недостающие данные.")
    return "\n\n".join(parts)


def _fmt_registration_complete(d: dict) -> str:
    summary = "\n".join(f"  {f['label']}: {f['value']}" for f in d["fields"])
    if d.get("aliases"):
        summary += f"\n  псевдонимы: {', '.join(d['aliases'])}"
    text = f"Ваши данные:\n{summary}\n\nВы добавлены в систему!"
    if d.get("secret_code"):
        text += f"\n\nВаш секретный код: *{d['secret_code']}*."
    return text


def _fmt_invoice_admin_caption(d: dict) -> str:
    return (f"{d['name']} ({d['contractor_type']}) — {d['month']}\n"
            f"Сумма: {d['amount']} ₽\n\n"
            "Ответьте на это сообщение ссылкой из Легиума.")


def _fmt_invoice_prompt(d: dict) -> str:
    return (f"У вас {d['pub_word']} за {d['month']}.\n"
            f"{d['explanation']}\n\n"
            "Отправьте другую сумму или напишите «ок» для подтверждения.")


def _fmt_upload_result(d: dict) -> str:
    text = f"Загружено {d['count']} записей в Airtable."
    if d.get("review_count"):
        text += f"\n⚠ {d['review_count']} записей требуют проверки (NEEDS REVIEW)."
    return text


def _fmt_new_registration(d: dict) -> str:
    text = f"Новая регистрация ({d['contractor_type']}):\n\n{d['raw_text']}"
    parsed = d.get("parsed_data", {})
    if parsed:
        formatted = "\n".join(f"  {k}: {v}" for k, v in parsed.items())
        text += f"\n\nРаспознанные данные:\n{formatted}"
    return text


def _fmt_document_received(d: dict) -> str:
    text = f"Документ от {d['sender']}:"
    if d.get("drive_link"):
        text += f"\nСохранено на Drive: {d['drive_link']}"
    return text


_FORMATTERS = {
    "contractor_info": _fmt_contractor_info,
    "articles_list": _fmt_articles_list,
    "operation_summary": _fmt_operation_summary,
    "orphan_list": _fmt_orphan_list,
    "fuzzy_suggestions": _fmt_fuzzy_suggestions,
    "registration_progress": _fmt_registration_progress,
    "registration_complete": _fmt_registration_complete,
    "invoice_admin_caption": _fmt_invoice_admin_caption,
    "invoice_prompt": _fmt_invoice_prompt,
    "upload_result": _fmt_upload_result,
    "new_registration": _fmt_new_registration,
    "document_received": _fmt_document_received,
}


def _resolve_text(m: dict) -> str:
    """Get display text from a message, formatting structured data if present."""
    data = m.get("data")
    if data:
        formatter = _FORMATTERS.get(data.get("type"))
        if formatter:
            return formatter(data)
    return m.get("text", "")


# ── Rendering ────────────────────────────────────────────────────────

def _build_keyboard(data: list[list[dict]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=b["text"], callback_data=b["data"]) for b in row]
        for row in data
    ])


async def render(message, state, result: dict) -> None:
    """Render an interact response: send messages, apply FSM, send side messages."""
    await _send_main_messages(message, result.get("messages", []))
    await _send_side_messages(result.get("side_messages", []))
    await _apply_fsm(state, result)


async def _send_main_messages(message, messages: list[dict]) -> None:
    for m in messages:
        sent = await _send_message_to_chat(message.chat.id, m, reply_message=message)
        if sent:
            _track_admin_reply(message.chat.id, sent.message_id, m)


async def _send_side_messages(side_messages: list[dict]) -> None:
    for sm in side_messages:
        try:
            chat_id = sm["chat_id"]
            sent = await _send_message_to_chat(chat_id, sm)
            if sent:
                _track_admin_reply(chat_id, sent.message_id, sm)
        except Exception:
            logger.warning("Failed to send side message to %s", sm.get("chat_id"), exc_info=True)


async def _send_message_to_chat(chat_id: int, m: dict, reply_message=None):
    keyboard = _build_keyboard(m["keyboard"]) if m.get("keyboard") else None
    text = _resolve_text(m)

    if m.get("file_b64"):
        doc = BufferedInputFile(
            base64.b64decode(m["file_b64"]),
            filename=m.get("filename", "file"),
        )
        return await bot.send_document(chat_id, doc, caption=text or None, reply_markup=keyboard)
    if text and reply_message:
        return await _send(reply_message, text, reply_markup=keyboard)
    if text:
        return await bot.send_message(chat_id, text)
    return None


def _track_admin_reply(chat_id: int, message_id: int, m: dict) -> None:
    track = m.get("track")
    if track and track.get("type") == "admin_reply":
        _admin_reply_map[(chat_id, message_id)] = (
            track["contractor_telegram"], track["contractor_id"],
        )


async def _apply_fsm(state, result: dict) -> None:
    if "fsm_state" in result:
        if result["fsm_state"] is None:
            await state.clear()
        else:
            from telegram_bot.router import ContractorStates  # noqa: PLC0415 (circular import)
            target = getattr(ContractorStates, result["fsm_state"], None)
            if target:
                await state.set_state(target)
    if "fsm_data" in result:
        await state.set_data(result["fsm_data"])
