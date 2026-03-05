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
            from backend.infrastructure.gateways.republic_gateway import RepublicGateway
            from backend.domain.use_cases.ingest_articles import IngestArticles
            from backend.wiring import create_memory_service

            today = datetime.now(cet).strftime("%Y-%m-%d")
            republic = RepublicGateway()
            posts = await asyncio.to_thread(republic.fetch_posts_by_date, today, today)
            if posts:
                articles = [
                    {"title": p["title"], "url": p["url"], "content": p.get("content", "")}
                    for p in posts
                ]
                memory = create_memory_service()
                ingest = IngestArticles(memory=memory)
                entry_ids = await asyncio.to_thread(ingest.execute, articles)
                logger.info("Daily ingest: %d articles ingested for %s", len(entry_ids), today)
            else:
                logger.info("Daily ingest: no articles found for %s", today)
        except Exception:
            logger.exception("Daily article ingest failed")


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
    asyncio.create_task(daily_article_ingest_task())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
