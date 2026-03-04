"""Email background task."""

from __future__ import annotations

import asyncio
import logging

from common.config import ADMIN_TELEGRAM_IDS, EMAIL_ADDRESS, EMAIL_IDLE_TIMEOUT, EMAIL_ERROR_RETRY_DELAY
from telegram_bot.handler_utils import _inbox
from telegram_bot.handlers.support_handlers import _send_support_draft, _send_editorial

logger = logging.getLogger(__name__)

__all__ = [
    "email_listener_task",
]


async def email_listener_task() -> None:
    """Background task: listen for new emails, classify, and send to admin."""
    if not ADMIN_TELEGRAM_IDS:
        logger.warning("No admin IDs configured, email listener disabled")
        return
    admin_id = ADMIN_TELEGRAM_IDS[0]
    logger.info("Email listener started for %s", EMAIL_ADDRESS)
    while True:
        try:
            has_new = await asyncio.to_thread(_inbox.idle_wait, EMAIL_IDLE_TIMEOUT)
            if not has_new:
                continue
            emails = await asyncio.to_thread(_inbox.fetch_unread)
            for em in emails:
                result = await asyncio.to_thread(_inbox.process, em)
                if not result:
                    continue
                if result.category == "tech_support":
                    await _send_support_draft(admin_id, result.draft)
                elif result.category == "editorial":
                    await _send_editorial(admin_id, result.editorial)
        except Exception as e:
            logger.exception("Email listener error: %s", e)
            await asyncio.sleep(EMAIL_ERROR_RETRY_DELAY)
