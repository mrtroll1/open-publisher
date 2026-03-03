"""Shared helpers and module-level state used across handler modules."""

from __future__ import annotations

import asyncio
import logging

from aiogram import types
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest

from backend.wiring import create_db, create_inbox_service, create_knowledge_retriever
from backend.domain.services.compose_request import set_retriever
from telegram_bot.bot_helpers import bot, get_contractors, md_to_tg_html, prev_month
from telegram_bot import replies
from backend import find_contractor, find_contractor_by_id, find_contractor_by_telegram_id, fuzzy_find

logger = logging.getLogger(__name__)

_db = create_db()
_inbox = create_inbox_service()
set_retriever(create_knowledge_retriever())

# Maps (admin_chat_id, bot_message_id) -> (contractor_telegram_id, contractor_id)
# so admin can reply to a notification and the reply gets forwarded.
_admin_reply_map: dict[tuple[int, int], tuple[str, str]] = {}

# Maps (admin_chat_id, bot_message_id) -> email uid
# so admin can reply to a support draft message.
_support_draft_map: dict[tuple[int, int], str] = {}

__all__ = [
    "send_typing",
    "parse_month_arg",
    "get_current_contractor",
    "get_contractor_by_id",
    "_safe_edit_text",
    "_send_html",
    "_save_turn",
    "_parse_flags",
    "_find_contractor_or_suggest",
    "_db",
    "_inbox",
    "_admin_reply_map",
    "_support_draft_map",
]


async def send_typing(chat_id: int) -> None:
    await bot.send_chat_action(chat_id, ChatAction.TYPING)


async def get_current_contractor(telegram_id: int) -> "Contractor | None":
    contractors = await get_contractors()
    return find_contractor_by_telegram_id(telegram_id, contractors)


async def get_contractor_by_id(contractor_id: str) -> "Contractor | None":
    contractors = await get_contractors()
    return find_contractor_by_id(contractor_id, contractors)


def parse_month_arg(args: list[str]) -> str:
    """Extract month from command args, defaulting to prev_month()."""
    return args[1].strip() if len(args) > 1 else prev_month()


async def _safe_edit_text(message, text: str, **kwargs) -> None:
    try:
        await message.edit_text(text, **kwargs)
    except TelegramBadRequest:
        pass


async def _send_html(message: types.Message, text: str, **kwargs) -> types.Message:
    """Send with markdown→HTML conversion; fall back to plain text on parse error."""
    try:
        return await message.answer(md_to_tg_html(text), parse_mode="HTML", **kwargs)
    except TelegramBadRequest:
        return await message.answer(text, **kwargs)


async def _save_turn(
    message: types.Message, sent: types.Message,
    user_text: str, bot_text: str, metadata: dict,
    parent_id: str | None = None,
) -> None:
    """Save user+assistant conversation turn to DB. Never raises.

    Args:
        parent_id: conversation entry id of the message being replied to.
                   Links the user entry into an existing reply chain.
    """
    try:
        channel = "group" if message.chat.type in ("group", "supergroup") else "dm"
        meta = {**metadata, "channel": channel}
        user_entry_id = await asyncio.to_thread(
            _db.save_conversation,
            chat_id=message.chat.id, user_id=message.from_user.id,
            role="user", content=user_text,
            reply_to_id=parent_id,
            message_id=message.message_id, metadata=meta,
        )
        await asyncio.to_thread(
            _db.save_conversation,
            chat_id=message.chat.id, user_id=message.from_user.id,
            role="assistant", content=bot_text,
            reply_to_id=user_entry_id, message_id=sent.message_id, metadata=meta,
        )
    except Exception:
        logger.exception("Failed to save conversation turn")


def _parse_flags(text: str) -> tuple[bool, bool, str]:
    """Parse -v (verbose) and -e (expert) flags. Returns (verbose, expert, rest)."""
    verbose = False
    expert = False
    while text:
        if text.startswith("-v ") or text.startswith("verbose "):
            verbose = True
            text = text.split(None, 1)[1] if " " in text else ""
        elif text.startswith("-e ") or text.startswith("expert "):
            expert = True
            text = text.split(None, 1)[1] if " " in text else ""
        else:
            break
    return verbose, expert, text


async def _find_contractor_or_suggest(
    raw_name: str, message: types.Message,
) -> "Contractor | None":
    contractors = await get_contractors()
    contractor = find_contractor(raw_name, contractors)
    if contractor:
        return contractor
    matches = fuzzy_find(raw_name, contractors, threshold=0.4)
    if matches:
        suggestions = "\n".join(
            f"  - {c.display_name} ({c.type.value})" for c, _ in matches[:5]
        )
        await message.answer(replies.lookup.fuzzy_suggestions.format(suggestions=suggestions))
    else:
        await message.answer(replies.lookup.not_found)
    return None
