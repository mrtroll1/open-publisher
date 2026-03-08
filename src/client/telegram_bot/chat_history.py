"""Fetch chat history via Telethon (MTProto) using the bot token."""

from __future__ import annotations

import logging
from datetime import datetime

from telethon import TelegramClient
from telethon.sessions import MemorySession

from telegram_bot.config import TELEGRAM_API_HASH, TELEGRAM_API_ID, TELEGRAM_BOT_TOKEN

logger = logging.getLogger(__name__)


async def fetch_chat_messages(
    chat_id: int,
    month: str | None = None,
    limit: int = 5000,
) -> list[dict]:
    """Fetch message history from a chat using Telethon bot client.

    Args:
        chat_id: Telegram chat ID
        month: optional 'YYYY-MM' to filter by month
        limit: max messages to fetch

    Returns:
        List of {sender, text, date} dicts, oldest first.
    """
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        raise RuntimeError(
            "TELEGRAM_API_ID and TELEGRAM_API_HASH required for chat history. "
            "Get them from https://my.telegram.org"
        )

    offset_date, min_date = _parse_month_range(month)

    client = TelegramClient(MemorySession(), TELEGRAM_API_ID, TELEGRAM_API_HASH)
    await client.start(bot_token=TELEGRAM_BOT_TOKEN)

    try:
        messages = []
        async for msg in client.iter_messages(
            chat_id, limit=limit, offset_date=offset_date,
        ):
            if not msg.text:
                continue
            if min_date and msg.date.replace(tzinfo=None) < min_date:
                break
            sender_name = _get_sender_name(msg)
            messages.append({
                "sender": sender_name,
                "text": msg.text,
                "date": msg.date.isoformat(),
            })
        messages.reverse()  # oldest first
        return messages
    finally:
        await client.disconnect()


def _parse_month_range(month: str | None):
    """Return (offset_date, min_date) for Telethon iter_messages."""
    if not month:
        return None, None
    try:
        start = datetime.strptime(month, "%Y-%m")
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
        return end, start  # offset_date = end (fetch backwards from end), min_date = start
    except ValueError:
        return None, None


def _get_sender_name(msg) -> str:
    if msg.sender:
        if hasattr(msg.sender, "first_name"):
            name = msg.sender.first_name or ""
            if msg.sender.last_name:
                name += f" {msg.sender.last_name}"
            return name.strip() or str(msg.sender_id)
        if hasattr(msg.sender, "title"):
            return msg.sender.title
    return str(msg.sender_id or "?")
