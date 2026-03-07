"""Shared bot helpers: date utils, admin checks."""

from __future__ import annotations

import re
from datetime import date

from aiogram import Bot

from telegram_bot import backend_client
from telegram_bot.config import TELEGRAM_BOT_TOKEN

bot = Bot(token=TELEGRAM_BOT_TOKEN)


# ─── Date helpers ────────────────────────────────────────────────────

def prev_month() -> str:
    """Return previous month as 'YYYY-MM'."""
    today = date.today()
    if today.month == 1:
        return f"{today.year - 1}-12"
    return f"{today.year}-{today.month - 1:02d}"


def current_month() -> str:
    today = date.today()
    return f"{today.year}-{today.month:02d}"


# ─── Admin check ─────────────────────────────────────────────────────

_admin_ids: set[int] = set()


async def load_admin_ids() -> None:
    """Load admin telegram IDs from DB. Call once at bot startup."""
    ids = await backend_client.get_admin_telegram_ids()
    _admin_ids.clear()
    _admin_ids.update(ids)


def is_admin(user_id: int) -> bool:
    return user_id in _admin_ids


def get_admin_ids() -> set[int]:
    return _admin_ids


# ─── Markdown → Telegram HTML ────────────────────────────────────────

def md_to_tg_html(text: str) -> str:
    """Convert standard markdown to Telegram-compatible HTML."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"```(?:\w*)\n?(.*?)```", r"<pre>\1</pre>", text, flags=re.DOTALL)
    text = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", text)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text, flags=re.DOTALL)
