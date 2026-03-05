"""Support/tech support handlers."""

from __future__ import annotations

import asyncio
import json
import logging
import time

from aiogram import types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery

from common.models import EditorialItem, SupportDraft
from backend.domain.services import compose_request
from backend.domain.code_runner import run_claude_code
from backend.domain.healthcheck import run_healthchecks, format_healthcheck_results
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from telegram_bot import replies
from telegram_bot.bot_helpers import bot
from telegram_bot.handler_utils import (
    _db,
    _inbox,
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
    "_answer_tech_question",
    "cmd_support",
    "cmd_code",
    "cmd_health",
    "handle_code_rate_callback",
    "handle_support_callback",
    "handle_editorial_callback",
    "_send_support_draft",
    "_send_editorial",
]


def _answer_tech_question(question: str, verbose: bool, expert: bool,
                          on_event=None) -> str:
    gemini = GeminiGateway()

    needs_code = False
    try:
        prompt, model, _ = compose_request.tech_search_terms(question)
        t0 = time.time()
        result = gemini.call(prompt, model)
        latency_ms = int((time.time() - t0) * 1000)
        try:
            _db.log_classification("TECH_SEARCH_TERMS", model, prompt, json.dumps(result), latency_ms)
        except Exception:
            logger.warning("Failed to log classification for task=TECH_SEARCH_TERMS", exc_info=True)
        needs_code = bool(result.get("needs_code"))
    except Exception as e:
        logger.warning("Tech support triage failed: %s", e)

    if needs_code:
        return run_claude_code(question, verbose=verbose, expert=expert, mode="explore", on_event=on_event)

    prompt, model, _ = compose_request.tech_support_question(question, "", verbose)
    result = gemini.call(prompt, model)
    return result.get("answer", str(result))


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
        loop = asyncio.get_running_loop()

        async with ThinkingMessage(message, "Ищу ответ...") as thinking:
            def on_event(status: str) -> None:
                asyncio.run_coroutine_threadsafe(thinking.update(status), loop)

            answer = await asyncio.to_thread(_answer_tech_question, text, verbose, expert, on_event=on_event)
            sent = await thinking.finish_long(answer)
        await _save_turn(message, sent, text, answer, {"command": "tech_support"})
    except Exception as e:
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

    try:
        loop = asyncio.get_running_loop()

        async with ThinkingMessage(message, "Запускаю Claude Code...") as thinking:
            def on_event(status: str) -> None:
                asyncio.run_coroutine_threadsafe(thinking.update(status), loop)

            answer = await asyncio.to_thread(run_claude_code, text, verbose, expert, mode="changes", on_event=on_event)
            # Save to DB and build rating keyboard
            reply_markup = None
            try:
                task_id = await asyncio.to_thread(
                    _db.create_code_task,
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
        await _save_turn(message, sent, text, answer, {"command": "code"})
    except Exception as e:
        logger.exception("Claude Code execution failed")
        await message.answer(replies.admin.code_error)


async def cmd_health(message: types.Message, state: FSMContext) -> None:
    await send_typing(message.chat.id)
    results = await asyncio.to_thread(run_healthchecks)
    await _send(message, format_healthcheck_results(results))


async def handle_code_rate_callback(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    _, task_id, rating = parts
    try:
        await asyncio.to_thread(_db.rate_code_task, task_id, int(rating))
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

    draft = _inbox.get_pending_support(uid)
    if not draft:
        await _safe_edit_text(callback.message, replies.tech_support.expired)
        return

    if action == "send":
        await asyncio.to_thread(_inbox.approve_support, uid)
        await _safe_edit_text(callback.message, replies.tech_support.reply_sent.format(addr=draft.email.reply_to or draft.email.from_addr))
    elif action == "skip":
        await asyncio.to_thread(_inbox.skip_support, uid)
        await _safe_edit_text(callback.message, replies.tech_support.skipped.format(from_addr=draft.email.from_addr))


async def handle_editorial_callback(callback: CallbackQuery) -> None:
    """Handle forward/skip button presses for editorial items."""
    await callback.answer()
    parts = callback.data.split(":")
    if len(parts) != 3:
        return
    _, action, uid = parts

    item = _inbox.get_pending_editorial(uid)
    if not item:
        await _safe_edit_text(callback.message, replies.editorial.expired)
        return

    if action == "fwd":
        await asyncio.to_thread(_inbox.approve_editorial, uid)
        await _safe_edit_text(callback.message, replies.editorial.forwarded.format(from_addr=item.email.from_addr, subject=item.email.subject))
    elif action == "skip":
        await asyncio.to_thread(_inbox.skip_editorial, uid)
        await _safe_edit_text(callback.message, replies.editorial.skipped.format(from_addr=item.email.from_addr))


async def _send_support_draft(admin_id: int, draft: SupportDraft) -> None:
    em = draft.email
    body_preview = em.body[:500] + ("..." if len(em.body) > 500 else "")
    header = f"From: {em.from_addr}\n"
    if em.reply_to and em.reply_to != em.from_addr:
        header += f"Reply-To: {em.reply_to}\n"
    draft_header = replies.tech_support.draft_header if draft.can_answer else replies.tech_support.draft_header_uncertain
    text = (
        f"{header}"
        f"Subject: {em.subject}\n\n"
        f"{body_preview}\n\n"
        f"{draft_header}\n"
        f"{draft.draft_reply}"
    )
    buttons = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=replies.tech_support.btn_send, callback_data=f"support:send:{em.uid}"),
        InlineKeyboardButton(text=replies.tech_support.btn_skip, callback_data=f"support:skip:{em.uid}"),
    ]])
    sent = await bot.send_message(admin_id, text, reply_markup=buttons)
    _support_draft_map[(admin_id, sent.message_id)] = em.uid


async def _send_editorial(admin_id: int, item: EditorialItem) -> None:
    em = item.email
    body_preview = em.body[:500] + ("..." if len(em.body) > 500 else "")
    text = (
        f"Письмо в редакцию\n"
        f"From: {em.from_addr}\n"
        f"Subject: {em.subject}\n\n"
        f"{body_preview}"
    )
    if item.reply_to_sender:
        text += f"\n\n--- Автоответ ---\n{item.reply_to_sender}"
    buttons = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=replies.editorial.btn_forward, callback_data=f"editorial:fwd:{em.uid}"),
        InlineKeyboardButton(text=replies.editorial.btn_skip, callback_data=f"editorial:skip:{em.uid}"),
    ]])
    await bot.send_message(admin_id, text, reply_markup=buttons)
