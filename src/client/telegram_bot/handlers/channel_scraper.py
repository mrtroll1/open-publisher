"""Background task: periodically scrape competitor Telegram channels."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime

from telegram_bot import backend_client
from telegram_bot.chat_history import fetch_chat_messages
from telegram_bot.config import TELEGRAM_API_ID, TELEGRAM_SESSION

logger = logging.getLogger(__name__)

__all__ = ["channel_scraper_task"]

_DEFAULT_INTERVAL = 24 * 3600  # once a day


async def channel_scraper_task() -> None:
    """Poll backend for scrapable channels, fetch new messages, send for processing."""
    if not TELEGRAM_API_ID or not TELEGRAM_SESSION:
        logger.warning("Telethon not configured, channel scraper disabled")
        return

    interval = int(os.getenv("CHANNEL_SCRAPE_INTERVAL", str(_DEFAULT_INTERVAL)))
    logger.info("Channel scraper started (every %ds)", interval)

    while True:
        try:
            environments = await backend_client.list_scrapable_environments()
            for env in environments:
                await _scrape_one(env)
        except Exception:
            logger.exception("Channel scraper error")
        await asyncio.sleep(interval)


async def _scrape_one(env: dict) -> None:
    name = env["name"]
    handle = env.get("telegram_handle")
    if not handle:
        return

    last = env.get("last_summarized_at")
    since = datetime.fromisoformat(last) if isinstance(last, str) and last else None

    logger.info("Scraping %s (%s) since %s", name, handle, since)

    try:
        messages = await fetch_chat_messages(handle, since=since)
    except Exception:
        logger.exception("Failed to fetch messages from %s", handle)
        return

    if not messages:
        logger.info("No new messages in %s", handle)
        return

    logger.info("Fetched %d messages from %s, sending to backend", len(messages), handle)
    result = await backend_client.scrape_channel(messages, name)
    count = result.get("count", 0) if isinstance(result, dict) else 0
    logger.info("Scraped %s: daily digest stored" if count else "Scraped %s: nothing notable", name)
