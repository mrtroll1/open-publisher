"""Telegram bot entry point: loads flow declarations and starts polling."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Dispatcher, F

from telegram_bot.bot_helpers import bot
from telegram_bot.flow_engine import register_flows
from telegram_bot.flow_callbacks import (
    email_listener_task, handle_email_callback, handle_duplicate_callback, handle_non_document,
)
from telegram_bot.flows import bot_flows

logger = logging.getLogger(__name__)
dp = Dispatcher()
dp.callback_query.register(handle_email_callback, F.data.startswith("email:"))
dp.callback_query.register(handle_duplicate_callback, F.data.startswith("dup:"))
register_flows(dp, bot_flows)

# Catch photos/stickers/etc — must be after flows so it doesn't interfere
dp.message.register(handle_non_document, F.photo | F.sticker | F.video | F.voice | F.video_note)


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    logger.info("Starting bot...")
    asyncio.create_task(email_listener_task())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
