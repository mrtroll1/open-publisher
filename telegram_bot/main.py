"""Telegram bot entry point."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Dispatcher

from telegram_bot import backend_client
from telegram_bot.bot_helpers import bot
from telegram_bot.router import register_all, set_bot_commands
from telegram_bot.handlers.email_listener import email_listener_task

logger = logging.getLogger(__name__)
dp = Dispatcher()
register_all(dp)


async def daily_article_ingest_task():
    """Ingest today's articles every day at 6:30 AM CET."""
    from datetime import datetime, timezone, timedelta

    cet = timezone(timedelta(hours=1))
    while True:
        now = datetime.now(cet)
        target = now.replace(hour=6, minute=30, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        wait_seconds = (target - now).total_seconds()
        logger.info("Next article ingest at %s CET (in %.0fs)", target.strftime("%Y-%m-%d %H:%M"), wait_seconds)
        await asyncio.sleep(wait_seconds)

        try:
            today = datetime.now(cet).strftime("%Y-%m-%d")
            result = await backend_client.command(
                "ingest", f"{today} {today}",
                environment_id="default",
                user_id="",
            )
            count = result.get("count", 0) if isinstance(result, dict) else 0
            logger.info("Daily ingest: %d articles ingested for %s", count, today)
        except Exception:
            logger.exception("Daily article ingest failed")


async def knowledge_pipeline_task():
    """Run knowledge pipelines periodically."""
    from common.config import KNOWLEDGE_PIPELINE_INTERVAL
    while True:
        try:
            await backend_client.command(
                "knowledge_pipeline", "",
                environment_id="default",
                user_id="",
            )
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
    asyncio.create_task(daily_article_ingest_task())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
