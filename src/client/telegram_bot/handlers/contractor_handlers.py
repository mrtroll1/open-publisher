"""Thin contractor handlers — delegate to backend /interact, render response."""

from __future__ import annotations

import base64
import logging

from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from telegram_bot import backend_client
from telegram_bot.bot_helpers import bot, get_admin_ids, is_admin
from telegram_bot.handler_utils import send_typing
from telegram_bot.renderer import render

logger = logging.getLogger(__name__)

__all__ = [
    "handle_start", "handle_menu", "handle_sign_doc",
    "handle_update_payment_data", "handle_manage_redirects",
    "handle_type_selection", "handle_data_input", "handle_contractor_text",
    "handle_verification_code", "handle_amount_input", "handle_update_data",
    "handle_editor_source_name",
    "handle_duplicate_callback", "handle_editor_source_callback",
    "handle_linked_menu_callback",
    "handle_document", "handle_non_document",
]


async def _interact(message: types.Message, state: FSMContext, action: str,
                    extra_payload: dict = None) -> None:
    payload = {"text": message.text or ""}
    if extra_payload:
        payload.update(extra_payload)
    fsm_state = await state.get_state()
    fsm_data = await state.get_data()
    result = await backend_client.interact(
        action=action,
        payload=payload,
        context={
            "user_id": message.from_user.id,
            "chat_id": message.chat.id,
            "is_admin": is_admin(message.from_user.id),
            "fsm_state": fsm_state,
            "fsm_data": fsm_data,
            "admin_ids": list(get_admin_ids()),
        },
    )
    await render(message, state, result)


async def _interact_callback(callback: CallbackQuery, state: FSMContext,
                             action: str) -> None:
    await callback.answer()
    msg = callback.message
    fsm_state = await state.get_state()
    fsm_data = await state.get_data()
    result = await backend_client.interact(
        action=action,
        payload={"callback_data": callback.data},
        context={
            "user_id": callback.from_user.id,
            "chat_id": msg.chat.id,
            "is_admin": is_admin(callback.from_user.id),
            "fsm_state": fsm_state,
            "fsm_data": fsm_data,
            "admin_ids": list(get_admin_ids()),
        },
    )
    await render(msg, state, result)


# ── Commands ─────────────────────────────────────────────────────────

async def handle_start(message: types.Message, state: FSMContext) -> None:
    await _interact(message, state, "start")


async def handle_menu(message: types.Message, state: FSMContext) -> None:
    if is_admin(message.from_user.id):
        from telegram_bot import replies
        await state.clear()
        await message.answer(replies.menu.admin)
        return
    await _interact(message, state, "menu")


async def handle_sign_doc(message: types.Message, state: FSMContext) -> None:
    await state.clear()
    await send_typing(message.chat.id)
    await _interact(message, state, "sign_doc")


async def handle_update_payment_data(message: types.Message, state: FSMContext) -> None:
    await state.clear()
    await _interact(message, state, "update_payment_data")


async def handle_manage_redirects(message: types.Message, state: FSMContext) -> None:
    await state.clear()
    await send_typing(message.chat.id)
    await _interact(message, state, "manage_redirects")


# ── FSM inputs ───────────────────────────────────────────────────────

async def handle_contractor_text(message: types.Message, state: FSMContext) -> str | None:
    await send_typing(message.chat.id)
    await _interact(message, state, "free_text")
    return None  # FSM transitions handled by renderer


async def handle_type_selection(message: types.Message, state: FSMContext) -> str | None:
    await _interact(message, state, "type_selection")
    return None


async def handle_data_input(message: types.Message, state: FSMContext) -> str | None:
    await _interact(message, state, "data_input")
    return None


async def handle_verification_code(message: types.Message, state: FSMContext) -> str | None:
    await _interact(message, state, "verification_code")
    return None


async def handle_amount_input(message: types.Message, state: FSMContext) -> str | None:
    await send_typing(message.chat.id)
    await _interact(message, state, "amount_input")
    return None


async def handle_update_data(message: types.Message, state: FSMContext) -> str | None:
    await _interact(message, state, "update_data")
    return None


async def handle_editor_source_name(message: types.Message, state: FSMContext) -> str | None:
    await _interact(message, state, "editor_source_name")
    return None


# ── Callbacks ────────────────────────────────────────────────────────

async def handle_duplicate_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await _interact_callback(callback, state, "dup_callback")


async def handle_editor_source_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await _interact_callback(callback, state, "esrc_callback")


async def handle_linked_menu_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await _interact_callback(callback, state, "menu_callback")


# ── Files ────────────────────────────────────────────────────────────

async def handle_document(message: types.Message, state: FSMContext) -> None:
    if is_admin(message.from_user.id):
        return

    extra = {}
    if message.document:
        file = await bot.get_file(message.document.file_id)
        data = await bot.download_file(file.file_path)
        extra["file_b64"] = base64.b64encode(data.read()).decode()
        extra["filename"] = message.document.file_name or "document"
        extra["mime"] = message.document.mime_type or ""

    await _interact(message, state, "document", extra)

    # Forward the original Telegram document to admins (backend can't do this)
    admin_ids = get_admin_ids()
    for admin_id in admin_ids:
        if admin_id != message.from_user.id:
            try:
                await bot.forward_message(admin_id, message.chat.id, message.message_id)
            except Exception:
                pass


async def handle_non_document(message: types.Message, state: FSMContext) -> None:
    await _interact(message, state, "non_document")
