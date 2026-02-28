"""Email support: IMAP listener task + Telegram approval handlers."""

from __future__ import annotations

import asyncio
import logging

from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from common.config import ADMIN_TELEGRAM_IDS, EMAIL_ADDRESS
from common.models import SupportDraft
from backend.infrastructure.gateways.email_gateway import EmailGateway
from backend.domain.handle_support_email import HandleSupportEmail
from telegram_bot.bot_helpers import bot

logger = logging.getLogger(__name__)

_email_gw = EmailGateway()
_support = HandleSupportEmail()

# Pending drafts awaiting admin action: email_uid → SupportDraft
_pending: dict[str, SupportDraft] = {}

# Tracks which admin is in "edit mode" for an email: chat_id → email_uid
_editing: dict[int, str] = {}


async def email_listener_task() -> None:
    """Background task: listen for new emails and send drafts to admins."""

    logger.info("Email listener started for %s", EMAIL_ADDRESS)
    while True:
        try:
            has_new = await asyncio.to_thread(_email_gw.idle_wait, 300)
            if not has_new:
                continue
            emails = await asyncio.to_thread(_email_gw.fetch_unread)
            for incoming in emails:
                draft = await asyncio.to_thread(_support.execute, incoming)
                _pending[incoming.uid] = draft
                await _notify_admins(draft)
        except Exception as e:
            logger.exception("Email listener error: %s", e)
            await asyncio.sleep(30)


async def _notify_admins(draft: SupportDraft) -> None:
    """Send the email + draft to all admins with approval buttons."""
    em = draft.email
    body_preview = em.body[:500] + ("..." if len(em.body) > 500 else "")

    text = (
        f"From: {em.from_addr}\n"
        f"Subject: {em.subject}\n\n"
        f"{body_preview}\n\n"
        f"--- Draft reply ---\n"
        f"{draft.draft_reply}"
    )

    buttons = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Send", callback_data=f"email:send:{em.uid}"),
        InlineKeyboardButton(text="Edit", callback_data=f"email:edit:{em.uid}"),
        InlineKeyboardButton(text="Skip", callback_data=f"email:skip:{em.uid}"),
    ]])

    for admin_id in ADMIN_TELEGRAM_IDS:
        await bot.send_message(admin_id, text, reply_markup=buttons)


async def handle_email_callback(callback: types.CallbackQuery) -> None:
    """Handle approve/edit/skip button presses."""
    await callback.answer()
    parts = callback.data.split(":")
    if len(parts) != 3:
        return
    _, action, uid = parts

    draft = _pending.get(uid)
    if not draft:
        await callback.message.edit_text("(expired — email already handled)")
        return

    if action == "send":
        await _send_and_cleanup(callback.message, draft)
    elif action == "edit":
        _editing[callback.message.chat.id] = uid
        await callback.message.edit_text(
            f"Original email from {draft.email.from_addr}:\n"
            f"{draft.email.body[:300]}\n\n"
            "Send your corrected reply as a text message."
        )
    elif action == "skip":
        await asyncio.to_thread(_email_gw.mark_read, uid)
        _pending.pop(uid, None)
        await callback.message.edit_text(f"Skipped email from {draft.email.from_addr}")


def is_editing_email(message: types.Message) -> bool:
    """Filter: True if this admin is currently editing an email reply."""
    return message.chat.id in _editing


async def handle_email_edit_reply(message: types.Message) -> None:
    """Handle the admin's corrected reply text."""
    uid = _editing.pop(message.chat.id, None)
    if not uid:
        return

    draft = _pending.get(uid)
    if not draft:
        await message.answer("(expired — email already handled)")
        return

    draft.draft_reply = message.text
    await _send_and_cleanup(message, draft)


async def _send_and_cleanup(message: types.Message, draft: SupportDraft) -> None:
    """Send the reply email and clean up."""
    em = draft.email
    await asyncio.to_thread(
        _email_gw.send_reply, em.from_addr, em.subject, draft.draft_reply, em.message_id,
    )
    await asyncio.to_thread(_email_gw.mark_read, em.uid)
    _pending.pop(em.uid, None)
    await message.answer(f"Reply sent to {em.from_addr}")
