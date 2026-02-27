"""Shared bot helpers: date utils, admin checks."""

from __future__ import annotations

import asyncio
from datetime import date

from aiogram import Bot

from common.config import ADMIN_TELEGRAM_IDS, TELEGRAM_BOT_TOKEN
from common.models import Contractor
from backend import load_all_contractors

bot = Bot(token=TELEGRAM_BOT_TOKEN)


async def get_contractors() -> list[Contractor]:
    """Load contractors from the Google Sheets."""
    return await asyncio.to_thread(load_all_contractors)


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

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_TELEGRAM_IDS


