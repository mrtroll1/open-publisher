"""Shared helpers and module-level state used across handler modules."""

from __future__ import annotations

import logging

from aiogram import types
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest

from telegram_bot.bot_helpers import bot, get_contractors, md_to_tg_html, prev_month
from telegram_bot import backend_client, replies
from backend import find_contractor, find_contractor_by_id, find_contractor_by_telegram_id, fuzzy_find

logger = logging.getLogger(__name__)

# Maps (admin_chat_id, bot_message_id) -> (contractor_telegram_id, contractor_id)
# so admin can reply to a notification and the reply gets forwarded.
_admin_reply_map: dict[tuple[int, int], tuple[str, str]] = {}

# Maps (admin_chat_id, bot_message_id) -> email uid
# so admin can reply to a support draft message.
_support_draft_map: dict[tuple[int, int], str] = {}

# Maps (chat_id, bot_message_id) -> entry_id
# so admin can reply to a kedit message with new content.
_kedit_pending: dict[tuple[int, int], str] = {}

__all__ = [
    "send_typing",
    "ThinkingMessage",
    "parse_month_arg",
    "parse_date_range_arg",
    "get_current_contractor",
    "get_contractor_by_id",
    "resolve_environment_record",
    "resolve_environment",
    "resolve_user_context",
    "_safe_edit_text",
    "_send",
    "_send_html",
    "_save_turn",
    "_parse_flags",
    "_find_contractor_or_suggest",
    "_admin_reply_map",
    "_support_draft_map",
    "_kedit_pending",
]


async def send_typing(chat_id: int) -> None:
    await bot.send_chat_action(chat_id, ChatAction.TYPING)


class ThinkingMessage:
    """Async context manager that shows a status message while processing."""

    def __init__(self, message: types.Message, initial_text: str = "Думаю..."):
        self._message = message
        self._initial_text = initial_text
        self._status_msg: types.Message | None = None

    async def __aenter__(self) -> "ThinkingMessage":
        self._status_msg = await self._message.answer(self._initial_text)
        return self

    async def update(self, text: str) -> None:
        """Edit the status message in place."""
        if self._status_msg:
            try:
                await self._status_msg.edit_text(text)
            except TelegramBadRequest:
                pass

    async def finish(self, text: str, **kwargs) -> types.Message:
        """Edit the status message with the final short reply."""
        if self._status_msg:
            try:
                await self._status_msg.edit_text(text, **kwargs)
            except TelegramBadRequest:
                pass
        return self._status_msg

    async def finish_long(self, text: str, **kwargs) -> types.Message:
        """Delete status message, send full reply via _send_html (supports chunking)."""
        if self._status_msg:
            try:
                await self._status_msg.delete()
            except TelegramBadRequest:
                pass
        return await _send_html(self._message, text, **kwargs)

    async def __aexit__(self, *exc) -> None:
        pass


async def resolve_environment_record(chat_id: int) -> dict | None:
    """Return the full environment dict for a chat, or None if unbound."""
    return await backend_client.get_environment(chat_id=chat_id)


async def resolve_environment(chat_id: int) -> tuple[str, list[str] | None]:
    """Return (system_context, allowed_domains) for a chat, or ("", None) if unbound."""
    env = await backend_client.get_environment(chat_id=chat_id)
    if env is None:
        return "", None
    return env["system_context"], env.get("allowed_domains")


async def resolve_user_context(user_id: int) -> str:
    """Look up user by telegram_id, return formatted context or empty string."""
    return await backend_client.get_user_context(user_id)


async def get_current_contractor(telegram_id: int) -> "Contractor | None":
    contractors = await get_contractors()
    return find_contractor_by_telegram_id(telegram_id, contractors)


async def get_contractor_by_id(contractor_id: str) -> "Contractor | None":
    contractors = await get_contractors()
    return find_contractor_by_id(contractor_id, contractors)


def parse_month_arg(args: list[str]) -> str:
    """Extract month from command args, defaulting to prev_month()."""
    return args[1].strip() if len(args) > 1 else prev_month()


def parse_date_range_arg(args: list[str]) -> tuple[str, str]:
    """Extract date range from command args.

    /cmd YYYY-MM-DD YYYY-MM-DD  → explicit range
    /cmd YYYY-MM-DD             → single day
    /cmd                        → today
    """
    from datetime import date as _date
    if len(args) >= 3:
        return args[1].strip(), args[2].strip()
    if len(args) == 2:
        return args[1].strip(), args[1].strip()
    return _date.today().isoformat(), _date.today().isoformat()


async def _safe_edit_text(message, text: str, **kwargs) -> None:
    try:
        await message.edit_text(text, **kwargs)
    except TelegramBadRequest:
        pass


_TG_MAX = 4096


def _split_text(text: str, limit: int = _TG_MAX) -> list[str]:
    """Split text into chunks that fit Telegram's message limit, breaking at newlines."""
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return chunks


async def _send(message: types.Message, text: str, **kwargs) -> types.Message:
    """Send plain text, splitting long messages into multiple Telegram messages."""
    chunks = _split_text(text)
    last = None
    for chunk in chunks:
        last = await message.answer(chunk, **kwargs)
    return last


async def _send_html(message: types.Message, text: str, **kwargs) -> types.Message:
    """Send with markdown→HTML conversion; fall back to plain text on parse error.

    Splits long messages into multiple Telegram messages.
    """
    html = md_to_tg_html(text)
    chunks = _split_text(html)
    last = None
    for chunk in chunks:
        try:
            last = await message.answer(chunk, parse_mode="HTML", **kwargs)
        except TelegramBadRequest:
            last = await message.answer(chunk, **kwargs)
    return last


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
        user_entry_id = await backend_client.save_turn(
            chat_id=message.chat.id, user_id=message.from_user.id,
            role="user", content=user_text,
            reply_to_id=parent_id,
            message_id=message.message_id, metadata=meta,
        )
        await backend_client.save_turn(
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
            parts = text.split(None, 1)
            text = parts[1] if len(parts) > 1 else ""
        elif text.startswith("-e ") or text.startswith("expert "):
            expert = True
            parts = text.split(None, 1)
            text = parts[1] if len(parts) > 1 else ""
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
