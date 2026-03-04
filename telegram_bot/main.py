"""Telegram bot entry point."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Dispatcher

from telegram_bot.bot_helpers import bot
from telegram_bot.router import register_all, set_bot_commands
from telegram_bot.handlers.email_listener import email_listener_task

logger = logging.getLogger(__name__)
dp = Dispatcher()
register_all(dp)


async def knowledge_pipeline_task():
    """Run knowledge pipelines periodically."""
    from common.config import KNOWLEDGE_PIPELINE_INTERVAL
    from backend.wiring import create_memory_service, create_db
    from backend.domain.use_cases.run_knowledge_pipelines import run_scheduled_pipelines
    memory = create_memory_service()
    db = create_db()
    while True:
        try:
            await asyncio.to_thread(run_scheduled_pipelines, memory, db)
        except Exception:
            logger.exception("Knowledge pipeline failed")
        await asyncio.sleep(KNOWLEDGE_PIPELINE_INTERVAL)


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    logger.info("Starting bot...")
    await set_bot_commands(bot)
    asyncio.create_task(email_listener_task())
    asyncio.create_task(knowledge_pipeline_task())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
