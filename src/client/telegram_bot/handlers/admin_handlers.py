"""Thin admin handlers — delegate to backend /interact, render response."""

from __future__ import annotations

import base64
import logging
from datetime import datetime

from aiogram import types
from aiogram.fsm.context import FSMContext

from telegram_bot import backend_client, replies
from telegram_bot.bot_helpers import bot
from telegram_bot.chat_history import fetch_chat_messages
from telegram_bot.config import TELEGRAM_API_ID, TELEGRAM_SESSION
from telegram_bot.handler_utils import (
    ThinkingMessage,
    _admin_reply_map,
    _support_draft_map,
    parse_month_arg,
    resolve_environment_record,
    send_typing,
)
from telegram_bot.handlers.conversation_handlers import _handle_nl_reply, handle_kedit_reply
from telegram_bot.renderer import render

logger = logging.getLogger(__name__)

__all__ = [
    "_handle_draft_reply",
    "cmd_articles",
    "cmd_budget",
    "cmd_chatid",
    "cmd_env_summarize",
    "cmd_extract_knowledge",
    "cmd_generate",
    "cmd_generate_invoices",
    "cmd_lookup",
    "cmd_orphan_contractors",
    "cmd_send_global_invoices",
    "cmd_send_legium_links",
    "cmd_upload_to_airtable",
    "handle_admin_reply",
]


def _interact_context(message: types.Message) -> dict:
    return {"user_id": message.from_user.id, "chat_id": message.chat.id,
            "is_admin": True, "admin_ids": []}


async def _interact_cmd(message: types.Message, state: FSMContext,
                        action: str, extra_payload: dict | None = None) -> None:
    args = message.text.split(maxsplit=1)
    payload = {"text": args[1].strip() if len(args) > 1 else ""}
    if extra_payload:
        payload.update(extra_payload)
    thinking: ThinkingMessage | None = None

    async def _on_progress(stage: str, detail: str) -> None:
        nonlocal thinking
        txt = detail or stage
        if thinking is None:
            thinking = ThinkingMessage(message, txt)
            await thinking.__aenter__()
        else:
            await thinking.update(txt)

    result = await backend_client.interact_stream(
        action=action, payload=payload,
        context=_interact_context(message), on_progress=_on_progress,
    )
    if thinking:
        await thinking.__aexit__(None, None, None)
    await render(message, state, result)


# ── Coupled commands (delegated to backend /interact) ────────────────

async def cmd_generate(message: types.Message, state: FSMContext) -> None:
    await _interact_cmd(message, state, "admin_generate")


async def cmd_articles(message: types.Message, state: FSMContext) -> None:
    await _interact_cmd(message, state, "admin_articles")


async def cmd_lookup(message: types.Message, state: FSMContext) -> None:
    await _interact_cmd(message, state, "admin_lookup")


async def cmd_generate_invoices(message: types.Message, state: FSMContext) -> None:
    await _interact_cmd(message, state, "admin_batch_generate")


async def cmd_send_global_invoices(message: types.Message, state: FSMContext) -> None:
    await _interact_cmd(message, state, "admin_send_global")


async def cmd_send_legium_links(message: types.Message, state: FSMContext) -> None:
    await _interact_cmd(message, state, "admin_send_legium")


async def cmd_orphan_contractors(message: types.Message, state: FSMContext) -> None:
    await _interact_cmd(message, state, "admin_orphans")


async def cmd_upload_to_airtable(message: types.Message, state: FSMContext) -> None:
    """Parse an attached bank statement CSV and upload expenses to Airtable."""
    text = message.text or message.caption or ""
    args = text.split(maxsplit=1)

    if not message.document or len(args) < 2:
        await message.answer(replies.admin.upload_usage)
        return

    await send_typing(message.chat.id)

    file = await bot.get_file(message.document.file_id)
    file_bytes = await bot.download_file(file.file_path)
    file_b64 = base64.b64encode(file_bytes.read()).decode()

    result = await backend_client.interact(
        action="admin_upload_statement",
        payload={"file_b64": file_b64, "rate": args[1].strip()},
        context={"user_id": message.from_user.id, "chat_id": message.chat.id, "is_admin": True},
    )
    await render(message, state, result)


# ── Already-clean commands (use backend_client directly) ─────────────

async def cmd_budget(message: types.Message, _state: FSMContext) -> None:
    """Generate the budget payments sheet."""
    args = message.text.split(maxsplit=1)
    month = parse_month_arg(args)

    await message.answer(replies.admin.budget_generating.format(month=month))
    await send_typing(message.chat.id)

    try:
        result = await backend_client.command(
            "budget", month,
            environment_id=str(message.chat.id),
            user_id=str(message.from_user.id),
        )
        url = result.get("url", str(result)) if isinstance(result, dict) else str(result)
        await message.answer(replies.admin.budget_done.format(url=url))
    except Exception as e:
        logger.exception("Budget generation failed")
        await message.answer(replies.admin.budget_error.format(error=e))


async def cmd_extract_knowledge(message: types.Message, _state: FSMContext) -> None:
    """Extract memorable facts from unprocessed conversations in this chat."""
    await message.answer(replies.admin.extract_knowledge_start)
    await send_typing(message.chat.id)

    try:
        result = await backend_client.command(
            "extract_knowledge", str(message.chat.id),
            environment_id=str(message.chat.id),
            user_id=str(message.from_user.id),
        )
        count = result.get("count", 0) if isinstance(result, dict) else 0
        await message.answer(replies.admin.extract_knowledge_done.format(count=count))
    except Exception as e:
        logger.exception("Knowledge extraction failed")
        await message.answer(replies.admin.extract_knowledge_error.format(error=e))


async def cmd_env_summarize(message: types.Message, _state: FSMContext) -> None:
    """Pull chat history from Telegram and extract knowledge for the environment."""
    # Check env binding
    env = await resolve_environment_record(message.chat.id)
    if not env:
        await message.answer(replies.admin.env_summarize_no_env)
        return

    if not TELEGRAM_API_ID or not TELEGRAM_SESSION:
        await message.answer(replies.admin.env_summarize_no_telethon)
        return

    # Parse optional month arg
    args = message.text.split(maxsplit=1)
    month = args[1].strip() if len(args) > 1 else None

    # Detect forum topic
    topic_id = getattr(message, "message_thread_id", None)

    thinking: ThinkingMessage | None = None

    async def _on_progress(stage: str, detail: str) -> None:
        nonlocal thinking
        txt = detail or stage
        if thinking is None:
            thinking = ThinkingMessage(message, txt)
            await thinking.__aenter__()
        else:
            await thinking.update(txt)

    try:
        # Fetch history from Telegram via Telethon
        await _on_progress("fetch", "Загружаю историю чата...")
        since = _parse_last_summarized(env) if not month else None
        messages = await fetch_chat_messages(message.chat.id, month=month,
                                             topic_id=topic_id, since=since)
        if not messages:
            if thinking:
                await thinking.__aexit__(None, None, None)
            await message.answer(replies.admin.env_summarize_no_messages)
            return

        await _on_progress("fetch", f"Загружено {len(messages)} сообщений")

        # Send to backend for processing
        result = await backend_client.env_summarize_stream(
            messages=messages,
            environment=env["name"],
            month=month,
            on_progress=_on_progress,
        )

        count = result.get("count", 0) if isinstance(result, dict) else 0
        if thinking:
            await thinking.finish_long(f"Извлечено {count} единиц знаний из истории чата.")
        else:
            await message.answer(f"Извлечено {count} единиц знаний из истории чата.")

    except Exception as e:
        logger.exception("env_summarize failed")
        if thinking:
            await thinking.__aexit__(None, None, None)
        await message.answer(replies.admin.env_summarize_error.format(error=e))


def _parse_last_summarized(env: dict) -> datetime | None:
    last = env.get("last_summarized_at")
    if isinstance(last, str):
        return datetime.fromisoformat(last)
    if isinstance(last, datetime):
        return last
    return None


# ── Utility ──────────────────────────────────────────────────────────

async def cmd_chatid(message: types.Message, _state: FSMContext) -> None:
    await message.answer(f"Chat ID: `{message.chat.id}`", parse_mode="Markdown")


# ── Admin reply routing ──────────────────────────────────────────────

async def _try_legium_reply(message, state, key) -> bool:
    entry = _admin_reply_map.get(key)
    if not entry:
        return False
    contractor_tg, contractor_id = entry
    try:
        result = await backend_client.interact(
            action="admin_legium_reply",
            payload={"text": message.text.strip(), "contractor_id": contractor_id,
                     "contractor_telegram": contractor_tg},
            context={"user_id": message.from_user.id, "chat_id": message.chat.id, "is_admin": True},
        )
        await render(message, state, result)
        del _admin_reply_map[key]
    except Exception as e:
        await message.answer(replies.invoice.legium_send_error.format(error=e))
    return True


async def handle_admin_reply(message: types.Message, state: FSMContext) -> None:
    reply = message.reply_to_message
    if not reply:
        return
    key = (message.chat.id, reply.message_id)
    if await _try_legium_reply(message, state, key):
        return
    uid = _support_draft_map.get(key)
    if uid:
        await _handle_draft_reply(message, uid)
        del _support_draft_map[key]
        return
    if await handle_kedit_reply(message):
        return
    await _handle_nl_reply(message, state)


async def _handle_draft_reply(message: types.Message, uid: str) -> None:
    draft = await backend_client.get_pending_support(uid)
    if not draft:
        await message.reply(replies.tech_support.expired)
        return

    text = message.text.strip()

    _GREETING_PREFIXES = ("здравствуйте", "добрый", "привет", "уважаем", "hi ", "hello", "dear")
    text_lower = text.lower().strip()
    is_replacement = any(text_lower.startswith(p) for p in _GREETING_PREFIXES) or len(text) > 100

    if is_replacement:
        await backend_client.update_and_approve_support(uid, message.text)
        addr = draft.get("reply_to") or draft.get("from_addr", "")
        await message.reply(replies.tech_support.replacement_sent.format(addr=addr))
    else:
        await backend_client.skip_support(uid)
        await backend_client.store_feedback(text, "tech_support")
        await message.reply(replies.tech_support.feedback_noted)
