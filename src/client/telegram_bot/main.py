"""Telegram bot entry point."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Dispatcher

from telegram_bot.bot_helpers import bot, load_admin_ids
from telegram_bot.handlers.channel_scraper import channel_scraper_task
from telegram_bot.handlers.email_listener import email_listener_task
from telegram_bot.handlers.goal_notifications import goal_notification_task
from telegram_bot.router import register_all, set_bot_commands

logger = logging.getLogger(__name__)
dp = Dispatcher()
register_all(dp)

_background_tasks: set[asyncio.Task] = set()


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    logger.info("Starting bot...")
    await load_admin_ids()
    await set_bot_commands(bot)
    for coro in (email_listener_task(), channel_scraper_task(), goal_notification_task()):
        task = asyncio.create_task(coro)
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
