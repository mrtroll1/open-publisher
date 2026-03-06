"""Email background task."""

from __future__ import annotations

import asyncio
import logging
import os
from telegram_bot import backend_client
from telegram_bot.bot_helpers import get_admin_ids
from telegram_bot.handlers.support_handlers import _send_support_draft, _send_editorial

logger = logging.getLogger(__name__)

__all__ = [
    "email_listener_task",
]


async def email_listener_task() -> None:
    """Background task: poll for new emails, classify, and send to admin.

    Uses backend API for inbox operations. Polls periodically since
    IMAP IDLE can't go through HTTP.
    """
    admin_ids = get_admin_ids()
    if not admin_ids:
        logger.warning("No admin IDs configured, email listener disabled")
        return
    admin_id = next(iter(admin_ids))
    poll_interval = int(os.getenv("EMAIL_POLL_INTERVAL", 300))
    logger.info("Email listener started (poll every %ds)", poll_interval)
    while True:
        try:
            result = await backend_client.fetch_unread()
            if result and isinstance(result, list):
                for item in result:
                    category = item.get("category")
                    if category == "tech_support" and item.get("draft"):
                        await _send_support_draft(admin_id, item["draft"])
                    elif category == "editorial" and item.get("editorial"):
                        await _send_editorial(admin_id, item["editorial"])
        except Exception as e:
            logger.exception("Email listener error: %s", e)
        await asyncio.sleep(poll_interval)
