"""Teaching/knowledge/NL conversation handlers."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

from aiogram import types
from aiogram.fsm.context import FSMContext

from backend.domain.services import compose_request
from backend.domain.services.compose_request import _get_retriever
from backend.domain.services.command_classifier import CommandClassifier

_VALID_SCOPES = {"general", "tech_support", "contractor", "identity", "support_triage", "email_inbox", "code"}
_VALID_TIERS = {"core", "domain"}
from backend.domain.services.conversation_service import (
    build_conversation_context,
    format_reply_chain as _format_reply_chain,
    generate_nl_reply,
)
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from telegram_bot import replies
from telegram_bot.handler_utils import _db, _save_turn, _send, _send_html, send_typing

logger = logging.getLogger(__name__)

_TEACHING_KEYWORDS = ("запомни", "учти", "имей в виду", "remember")

# All commands available for admin /nl classification
_ADMIN_NL_DESCRIPTIONS: dict[str, str] = {
    "health": "Проверка доступности сайтов и подов",
    "support": "Любой вопрос о продукте, сайте, функциях, настройках, подписке или техподдержке",
    "articles": "Статьи контрагента за месяц",
    "lookup": "Информация о контрагенте",
    "generate": "Сгенерировать документ для контрагента",
    "generate_invoices": "Сгенерировать счета для всех контрагентов",
    "send_global_invoices": "Отправить глобальные счета контрагентам в Telegram",
    "send_legium_links": "Отправить ссылки на Легиум контрагентам в Telegram",
    "orphan_contractors": "Показать несовпадения между бюджетом и контрагентами",
    "budget": "Расчёт бюджета",
    "code": "Запустить Claude Code для ответов, требующих посмотреть или изменить код",
}

__all__ = [
    "cmd_nl",
    "cmd_teach",
    "cmd_knowledge",
    "cmd_forget",
    "cmd_kedit",
    "_classify_teaching_text",
    "_format_reply_chain",
    "_handle_nl_reply",
]


async def _handle_nl_reply(message: types.Message, state: FSMContext) -> bool:
    """Handle a conversational NL reply to a bot message. Returns True on success."""
    if await state.get_state() is not None:
        return False

    reply = message.reply_to_message
    if not reply:
        return False

    if not reply.from_user or not reply.from_user.is_bot:
        return False

    try:
        await send_typing(message.chat.id)

        # Detect teaching patterns — classify & store before LLM call, then continue
        user_text_lower = (message.text or "").lower()
        if any(kw in user_text_lower for kw in _TEACHING_KEYWORDS):
            try:
                scope, tier = await _classify_teaching_text(message.text)
                retriever = _get_retriever()
                await asyncio.to_thread(retriever.store_teaching, message.text, scope=scope, tier=tier)
            except Exception:
                logger.exception("Failed to store NL teaching")

        # Build conversation history
        history, parent_id = await asyncio.to_thread(
            build_conversation_context,
            message.chat.id, reply.message_id, reply.text or "", _db,
        )

        # Generate reply via LLM
        retriever = _get_retriever()
        answer = await asyncio.to_thread(
            generate_nl_reply,
            message.text, history, retriever, GeminiGateway(),
        )

        sent = await _send_html(message, answer, reply_to_message_id=message.message_id)
        await _save_turn(message, sent, message.text, answer, {"command": "nl_reply"},
                         parent_id=parent_id)
        return True
    except Exception:
        logger.exception("NL reply failed")
        return False


async def cmd_nl(message: types.Message, state: FSMContext) -> None:
    """Natural language command classification for admin DM."""
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer("Использование: /nl <текст команды на естественном языке>")
        return

    text = args[1].strip()

    try:
        classifier = CommandClassifier(GeminiGateway())
        result = await asyncio.to_thread(
            classifier.classify, text, _ADMIN_NL_DESCRIPTIONS,
        )
    except Exception:
        logger.exception("NL classification failed")
        await message.answer("Не удалось классифицировать команду.")
        return

    if not result.classified:
        reply = result.reply or "Не удалось определить команду."
        sent = await _send_html(message, reply)
        await _save_turn(message, sent, text, reply, {"command": "nl_fallback"})
        return

    cmd = result.classified.command
    cmd_args = result.classified.args or text

    # Build the handler map lazily (avoid circular imports)
    from telegram_bot.handlers.group_handlers import _GROUP_COMMAND_HANDLERS
    from telegram_bot.handlers.admin_handlers import (
        cmd_generate, cmd_generate_invoices, cmd_send_global_invoices,
        cmd_send_legium_links, cmd_orphan_contractors, cmd_budget,
    )
    from telegram_bot.handlers.support_handlers import cmd_code

    handlers: dict[str, Callable] = {
        **_GROUP_COMMAND_HANDLERS,
        "generate": cmd_generate,
        "generate_invoices": cmd_generate_invoices,
        "send_global_invoices": cmd_send_global_invoices,
        "send_legium_links": cmd_send_legium_links,
        "orphan_contractors": cmd_orphan_contractors,
        "budget": cmd_budget,
        "code": cmd_code,
    }

    handler = handlers.get(cmd)
    if not handler:
        await message.answer(f"Команда {cmd} не найдена.")
        return

    # Temporarily rewrite .text (Message is a frozen Pydantic model)
    original_text = message.text
    object.__setattr__(message, "text", f"/{cmd} {cmd_args}" if cmd_args else f"/{cmd}")
    try:
        await handler(message, state)
    finally:
        object.__setattr__(message, "text", original_text)


async def _classify_teaching_text(text: str) -> tuple[str, str]:
    """Classify teaching text into (scope, tier) via Gemini.

    Fetches similar entries from the DB to give Gemini context for better classification.
    """
    retriever = _get_retriever()

    # Fetch similar entries as examples for Gemini
    similar = await asyncio.to_thread(retriever._db.search_knowledge,
                                      retriever._embed.embed_one(text), None, 5)
    examples_lines = []
    for e in similar:
        examples_lines.append(f"- [{e['tier']}] {e['scope']} / {e['title']}")
    examples = "\n".join(examples_lines) if examples_lines else ""

    gemini = GeminiGateway()
    prompt, model, keys = compose_request.classify_teaching(text, examples)
    result = await asyncio.to_thread(gemini.call, prompt, model)
    scope = result.get("scope", "general")
    tier = result.get("tier", "domain")
    if scope not in _VALID_SCOPES:
        scope = "general"
    if tier not in _VALID_TIERS:
        tier = "domain"
    return scope, tier


async def cmd_teach(message: types.Message, state: FSMContext) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer(replies.teach.usage)
        return

    text = args[1].strip()
    try:
        scope, tier = await _classify_teaching_text(text)
        retriever = _get_retriever()
        await asyncio.to_thread(retriever.store_teaching, text, scope=scope, tier=tier)
    except Exception:
        logger.exception("Failed to store teaching")
        await message.answer("Не удалось сохранить.")
        return
    await message.answer(replies.teach.stored_fmt.format(scope=scope, tier=tier))


async def cmd_knowledge(message: types.Message, state: FSMContext) -> None:
    parts = message.text.split()[1:]  
    verbose = "-v" in parts
    if verbose:
        parts.remove("-v")

    scope = parts[0] if len(parts) >= 1 else None
    tier = parts[1] if len(parts) >= 2 else None

    try:
        entries = await asyncio.to_thread(_db.list_knowledge, scope=scope, tier=tier)
    except Exception:
        logger.exception("Failed to list knowledge")
        await message.answer("Ошибка при загрузке записей.")
        return

    if not entries:
        await message.answer(replies.knowledge.empty)
        return

    template = replies.knowledge.entry_verbose if verbose else replies.knowledge.entry

    # Group by (tier, scope) for readability
    grouped: dict[tuple[str, str], list[tuple[int, dict]]] = {}
    for i, e in enumerate(entries, 1):
        key = (e["tier"], e["scope"])
        grouped.setdefault(key, []).append((i, e))

    lines = [replies.knowledge.header.format(count=len(entries))]
    for (tier_name, scope_name), items in grouped.items():
        lines.append(f"<b>[{tier_name}] {scope_name}</b>")
        for i, e in items:
            date = e["created_at"].strftime("%Y-%m-%d") if e.get("created_at") else "?"
            content = e.get("content", "")
            if content and len(content) > 120:
                content = content[:120] + "…"
            lines.append(template.format(
                i=i, tier=e["tier"], scope=e["scope"],
                title=e["title"], id=e["id"],
                source=e["source"], date=date,
                content=content,
            ))
        lines.append("")  # blank line between groups

    await _send(message, "\n".join(lines).rstrip(), parse_mode="HTML")


async def cmd_forget(message: types.Message, state: FSMContext) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer(replies.knowledge.forget_usage)
        return

    entry_id = args[1].strip()
    try:
        found = await asyncio.to_thread(_db.deactivate_knowledge, entry_id)
    except Exception:
        logger.exception("Failed to deactivate knowledge entry")
        await message.answer(replies.knowledge.not_found)
        return
    if not found:
        await message.answer(replies.knowledge.not_found)
        return
    await message.answer(replies.knowledge.forget_done)


async def cmd_kedit(message: types.Message, state: FSMContext) -> None:
    args = message.text.split(maxsplit=2)
    if len(args) < 3 or not args[2].strip():
        await message.answer(replies.knowledge.edit_usage)
        return

    entry_id = args[1].strip()
    new_content = args[2].strip()
    try:
        retriever = _get_retriever()
        embedding = await asyncio.to_thread(retriever._embed.embed_one, new_content)
        found = await asyncio.to_thread(_db.update_knowledge_entry, entry_id, new_content, embedding)
    except Exception:
        logger.exception("Failed to edit knowledge entry")
        await message.answer(replies.knowledge.not_found)
        return
    if not found:
        await message.answer(replies.knowledge.not_found)
        return
    await message.answer(replies.knowledge.edit_done)
