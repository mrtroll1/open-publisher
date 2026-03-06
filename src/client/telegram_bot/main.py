"""Telegram bot entry point."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Dispatcher

from telegram_bot.bot_helpers import bot, load_admin_ids
from telegram_bot.router import register_all, set_bot_commands
from telegram_bot.handlers.email_listener import email_listener_task

logger = logging.getLogger(__name__)
dp = Dispatcher()
register_all(dp)


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    logger.info("Starting bot...")
    await load_admin_ids()
    await set_bot_commands(bot)
    asyncio.create_task(email_listener_task())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
