"""Group chat handling."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

from aiogram import types
from aiogram.fsm.context import FSMContext

from common.config import BOT_USERNAME
from backend.domain.services.command_classifier import CommandClassifier
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from telegram_bot import replies
from telegram_bot.bot_helpers import bot
from telegram_bot.flow_dsl import GroupChatConfig
from telegram_bot.handler_utils import _save_turn, _send_html
from telegram_bot.handlers.support_handlers import cmd_health, cmd_support, cmd_code
from telegram_bot.handlers.admin_handlers import cmd_articles, cmd_lookup

logger = logging.getLogger(__name__)

_GROUP_COMMAND_HANDLERS: dict[str, Callable] = {
    "health": cmd_health,
    "support": cmd_support,
    "articles": cmd_articles,
    "lookup": cmd_lookup,
}

_COMMAND_DESCRIPTIONS: dict[str, str] = {
    "health": "Проверка доступности сайтов и подов",
    "support": "Любой вопрос о продукте, сайте, функциях, настройках, подписке или техподдержке",
    "articles": "Статьи контрагента за месяц",
    "lookup": "Информация о контрагенте",
}

__all__ = [
    "_extract_bot_mention",
    "_dispatch_group_command",
    "handle_group_message",
    "_GROUP_COMMAND_HANDLERS",
    "_COMMAND_DESCRIPTIONS",
]


def _extract_bot_mention(text: str, bot_username: str) -> str | None:
    prefix = f"@{bot_username}"
    if text.startswith(prefix + " ") or text.startswith(prefix + "\n"):
        return text[len(prefix):].strip()
    return None


async def _dispatch_group_command(
    command: str, args_text: str, message: types.Message, state: FSMContext,
) -> None:
    if command == "menu":
        await message.answer(replies.menu.group)
        return
    handler = _GROUP_COMMAND_HANDLERS.get(command)
    if not handler:
        return
    original_text = message.text
    new_text = f"/{command} {args_text}" if args_text else f"/{command}"
    object.__setattr__(message, "text", new_text)
    try:
        await handler(message, state)
    finally:
        object.__setattr__(message, "text", original_text)


async def handle_group_message(
    message: types.Message, state: FSMContext, group_config: GroupChatConfig,
) -> None:
    text = message.text or ""

    # Explicit command (e.g. /health, /support@bot_username)
    if text.startswith("/"):
        raw_cmd = text.split()[0].lstrip("/")
        # Strip @bot_username suffix from command
        if "@" in raw_cmd:
            raw_cmd = raw_cmd.split("@", 1)[0]
        if raw_cmd not in group_config.allowed_commands:
            return
        args = text.split(maxsplit=1)
        args_text = args[1] if len(args) > 1 else ""
        await _dispatch_group_command(raw_cmd, args_text, message, state)
        return

    # Natural language: @mention or reply to bot message
    if not group_config.natural_language:
        return

    clean_text = _extract_bot_mention(text, BOT_USERNAME)
    is_reply_to_bot = (
        message.reply_to_message
        and message.reply_to_message.from_user
        and message.reply_to_message.from_user.is_bot
    )

    if clean_text is None and not is_reply_to_bot:
        return

    if clean_text is None:
        clean_text = text

    available_commands = {
        cmd: _COMMAND_DESCRIPTIONS[cmd]
        for cmd in group_config.allowed_commands
        if cmd in _COMMAND_DESCRIPTIONS
    }
    if not available_commands:
        return

    try:
        classifier = CommandClassifier(GeminiGateway())
        result = await asyncio.to_thread(
            classifier.classify, clean_text, available_commands,
        )
    except Exception:
        logger.exception("Command classification failed in group chat")
        return

    if not result.classified:
        if is_reply_to_bot:
            # Lazy import to avoid circular dependency
            from telegram_bot.handlers.conversation_handlers import _handle_nl_reply
            if await _handle_nl_reply(message, state):
                return
        if result.reply:
            sent = await _send_html(message, result.reply)
            await _save_turn(message, sent, clean_text, result.reply,
                             {"command": "nl_fallback"})
        return

    await _dispatch_group_command(
        result.classified.command, result.classified.args or clean_text, message, state,
    )
