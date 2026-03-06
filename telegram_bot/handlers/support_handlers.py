"""Support/tech support handlers."""

from __future__ import annotations

import asyncio
import logging

from aiogram import types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery

from telegram_bot import backend_client, replies
from telegram_bot.bot_helpers import bot
from telegram_bot.handler_utils import (
    _parse_flags,
    _safe_edit_text,
    _save_turn,
    _send,
    _send_html,
    _support_draft_map,
    send_typing,
    ThinkingMessage,
)

logger = logging.getLogger(__name__)

__all__ = [
    "cmd_support",
    "cmd_code",
    "cmd_health",
    "handle_code_rate_callback",
    "handle_support_callback",
    "handle_editorial_callback",
    "_send_support_draft",
    "_send_editorial",
]


async def cmd_support(message: types.Message, state: FSMContext) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer(replies.admin.support_usage)
        return

    verbose, expert, text = _parse_flags(args[1].strip())
    if not text:
        await message.answer(replies.admin.support_no_question)
        return

    try:
        flags = ""
        if verbose:
            flags += "-v "
        if expert:
            flags += "-e "
        input_text = flags + text

        async with ThinkingMessage(message, "Ищу ответ...") as thinking:
            result = await backend_client.command(
                "support", input_text,
                environment_id=str(message.chat.id),
                user_id=str(message.from_user.id),
            )
            answer = result.get("reply", str(result)) if isinstance(result, dict) else str(result)
            sent = await thinking.finish_long(answer)
        await _save_turn(message, sent, text, answer, {"command": "tech_support"})
    except Exception:
        logger.exception("Support question failed")
        await message.answer(replies.admin.support_error)


async def cmd_code(message: types.Message, state: FSMContext) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer(replies.admin.code_usage)
        return

    verbose, expert, text = _parse_flags(args[1].strip())
    if not text:
        await message.answer(replies.admin.code_no_query)
        return

    # Check if replying to a previous Claude Code message — resume session
    resume_session_id = None
    reply = message.reply_to_message
    if reply and reply.from_user and reply.from_user.is_bot:
        try:
            conv = await backend_client.get_conversation_by_message_id(
                message.chat.id, reply.message_id,
            )
            if conv and conv.get("metadata", {}).get("claude_session_id"):
                resume_session_id = conv["metadata"]["claude_session_id"]
        except Exception:
            logger.debug("Could not look up session_id for reply", exc_info=True)

    try:
        flags = ""
        if verbose:
            flags += "-v "
        if expert:
            flags += "-e "
        if resume_session_id:
            flags += f"--resume={resume_session_id} "
        input_text = flags + text

        async with ThinkingMessage(message, "Запускаю Claude Code...") as thinking:
            result = await backend_client.command(
                "code", input_text,
                environment_id=str(message.chat.id),
                user_id=str(message.from_user.id),
            )
            answer = result.get("text", str(result)) if isinstance(result, dict) else str(result)
            session_id = result.get("session_id") if isinstance(result, dict) else None

            # Save to DB and build rating keyboard
            reply_markup = None
            try:
                task_id = await backend_client.create_code_task(
                    requested_by=str(message.from_user.id),
                    input_text=text,
                    output_text=answer,
                    verbose=verbose,
                )
                reply_markup = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text=str(i), callback_data=f"code_rate:{task_id}:{i}")
                    for i in range(1, 6)
                ]])
            except Exception:
                logger.exception("Failed to save code task to DB")
            sent = await thinking.finish_long(answer, reply_markup=reply_markup)
        meta = {"command": "code"}
        if session_id:
            meta["claude_session_id"] = session_id
        await _save_turn(message, sent, text, answer, meta)
    except Exception:
        logger.exception("Claude Code execution failed")
        await message.answer(replies.admin.code_error)


async def cmd_health(message: types.Message, state: FSMContext) -> None:
    await send_typing(message.chat.id)
    result = await backend_client.command(
        "health", "",
        environment_id=str(message.chat.id),
        user_id=str(message.from_user.id),
    )
    text = result.get("text", str(result)) if isinstance(result, dict) else str(result)
    await _send(message, text)


async def handle_code_rate_callback(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    _, task_id, rating = parts
    try:
        await backend_client.rate_code_task(task_id, int(rating))
    except Exception:
        logger.exception("Failed to save code task rating")
    await callback.answer("Оценка сохранена!")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass


async def handle_support_callback(callback: CallbackQuery) -> None:
    """Handle send/skip button presses for tech support drafts."""
    await callback.answer()
    parts = callback.data.split(":")
    if len(parts) != 3:
        return
    _, action, uid = parts

    draft = await backend_client.get_pending_support(uid)
    if not draft:
        await _safe_edit_text(callback.message, replies.tech_support.expired)
        return

    if action == "send":
        await backend_client.approve_support(uid)
        addr = draft.get("reply_to") or draft.get("from_addr", "")
        await _safe_edit_text(callback.message, replies.tech_support.reply_sent.format(addr=addr))
    elif action == "skip":
        await backend_client.skip_support(uid)
        await _safe_edit_text(callback.message, replies.tech_support.skipped.format(from_addr=draft.get("from_addr", "")))


async def handle_editorial_callback(callback: CallbackQuery) -> None:
    """Handle forward/skip button presses for editorial items."""
    await callback.answer()
    parts = callback.data.split(":")
    if len(parts) != 3:
        return
    _, action, uid = parts

    item = await backend_client.get_pending_editorial(uid)
    if not item:
        await _safe_edit_text(callback.message, replies.editorial.expired)
        return

    if action == "fwd":
        await backend_client.approve_editorial(uid)
        await _safe_edit_text(callback.message, replies.editorial.forwarded.format(
            from_addr=item.get("from_addr", ""), subject=item.get("subject", "")))
    elif action == "skip":
        await backend_client.skip_editorial(uid)
        await _safe_edit_text(callback.message, replies.editorial.skipped.format(
            from_addr=item.get("from_addr", "")))


async def _send_support_draft(admin_id: int, draft: dict) -> None:
    body_preview = draft["body"]
    header = f"From: {draft['from_addr']}\n"
    reply_to = draft.get("reply_to", "")
    if reply_to and reply_to != draft["from_addr"]:
        header += f"Reply-To: {reply_to}\n"
    draft_header = replies.tech_support.draft_header if draft.get("can_answer") else replies.tech_support.draft_header_uncertain
    text = (
        f"{header}"
        f"Subject: {draft['subject']}\n\n"
        f"{body_preview}\n\n"
        f"{draft_header}\n"
        f"{draft['draft_reply']}"
    )
    buttons = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=replies.tech_support.btn_send, callback_data=f"support:send:{draft['uid']}"),
        InlineKeyboardButton(text=replies.tech_support.btn_skip, callback_data=f"support:skip:{draft['uid']}"),
    ]])
    sent = await bot.send_message(admin_id, text, reply_markup=buttons)
    _support_draft_map[(admin_id, sent.message_id)] = draft["uid"]


async def _send_editorial(admin_id: int, item: dict) -> None:
    body_preview = item["body"]
    text = (
        f"Письмо в редакцию\n"
        f"From: {item['from_addr']}\n"
        f"Subject: {item['subject']}\n\n"
        f"{body_preview}"
    )
    if item.get("reply_to_sender"):
        text += f"\n\n--- Автоответ ---\n{item['reply_to_sender']}"
    buttons = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=replies.editorial.btn_forward, callback_data=f"editorial:fwd:{item['uid']}"),
        InlineKeyboardButton(text=replies.editorial.btn_skip, callback_data=f"editorial:skip:{item['uid']}"),
    ]])
    await bot.send_message(admin_id, text, reply_markup=buttons)
