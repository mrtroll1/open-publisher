"""Telegram bot entry point: loads flow declarations and starts polling."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Dispatcher, F

from telegram_bot.bot_helpers import bot
from telegram_bot.flow_engine import register_flows, set_bot_commands
from telegram_bot.flow_callbacks import (
    email_listener_task, handle_support_callback, handle_editorial_callback,
    handle_duplicate_callback, handle_editor_source_callback,
    handle_linked_menu_callback, handle_non_document,
)
from telegram_bot.flows import bot_flows

logger = logging.getLogger(__name__)
dp = Dispatcher()
dp.callback_query.register(handle_support_callback, F.data.startswith("support:"))
dp.callback_query.register(handle_editorial_callback, F.data.startswith("editorial:"))
dp.callback_query.register(handle_duplicate_callback, F.data.startswith("dup:"))
dp.callback_query.register(handle_editor_source_callback, F.data.startswith("esrc:"))
dp.callback_query.register(handle_linked_menu_callback, F.data.startswith("menu:"))
register_flows(dp, bot_flows)

# Catch photos/stickers/etc — must be after flows so it doesn't interfere
dp.message.register(handle_non_document, F.photo | F.sticker | F.video | F.voice | F.video_note | F.audio)


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    logger.info("Starting bot...")
    await set_bot_commands(bot)
    asyncio.create_task(email_listener_task())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
