"""Explicit message router — single source of truth for all bot routing.

Text message routing (priority order inside _route_text):
  1. Group message         → handle_group_message()
  2. /command              → _DM_COMMANDS or _ADMIN_COMMANDS lookup
  3. Admin reply-to-msg    → handle_admin_reply()
  4. FSM state active      → _FSM_HANDLERS[state]
  5. Free text (catch-all) → handle_contractor_text()

Other message types (registered explicitly in register_all):
  - Callback queries: 6 handlers
  - Documents: handle_document()
  - Media (photo/sticker/etc): handle_non_document()
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

from aiogram import Dispatcher, F, types
from aiogram.enums import ChatAction
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import BotCommand

from common.config import BOT_USERNAME, EDITORIAL_CHAT_ID
from backend.domain.services.command_classifier import CommandClassifier
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from telegram_bot import replies
from telegram_bot.bot_helpers import is_admin
from telegram_bot.handler_utils import _save_turn, _send_html, resolve_environment, send_typing
from telegram_bot.handlers.support_handlers import cmd_health, cmd_support, cmd_code
from telegram_bot.handlers.admin_handlers import (
    cmd_generate, cmd_chatid, cmd_articles, cmd_lookup, cmd_budget,
    cmd_generate_invoices, cmd_send_global_invoices, cmd_send_legium_links,
    cmd_orphan_contractors, cmd_upload_to_airtable,
    handle_admin_reply,
)
from telegram_bot.handlers.contractor_handlers import (
    handle_start, handle_menu, handle_sign_doc,
    handle_update_payment_data, handle_manage_redirects,
    handle_contractor_text, handle_verification_code, handle_type_selection,
    handle_data_input, handle_amount_input, handle_update_data,
    handle_editor_source_name,
    handle_duplicate_callback, handle_editor_source_callback,
    handle_linked_menu_callback, handle_non_document, handle_document,
)
from telegram_bot.handlers.conversation_handlers import (
    cmd_nl, cmd_teach, cmd_knowledge, cmd_ksearch, cmd_forget, cmd_kedit,
)

logger = logging.getLogger(__name__)


# ── FSM States ────────────────────────────────────────────────────────

class ContractorStates(StatesGroup):
    lookup = State()
    waiting_verification = State()
    waiting_type = State()
    waiting_data = State()
    waiting_amount = State()
    waiting_update_data = State()
    waiting_editor_source_name = State()


# ── FSM Tables ────────────────────────────────────────────────────────

# state name → handler function
_FSM_HANDLERS: dict[str, Callable] = {
    "lookup": handle_contractor_text,
    "waiting_verification": handle_verification_code,
    "waiting_type": handle_type_selection,
    "waiting_data": handle_data_input,
    "waiting_amount": handle_amount_input,
    "waiting_update_data": handle_update_data,
    "waiting_editor_source_name": handle_editor_source_name,
}

# (from_state, handler_return_key) → (target_state | "end", transition_message | None)
_FSM_TRANSITIONS: dict[tuple[str, str], tuple[str, str | None]] = {
    ("lookup", "register"):                 ("waiting_type", replies.registration.begin),
    ("waiting_verification", "verified"):   ("end", None),
    ("waiting_verification", "invoice"):    ("waiting_amount", None),
    ("waiting_type", "valid"):              ("waiting_data", None),
    ("waiting_data", "complete"):           ("end", None),
    ("waiting_data", "invoice"):            ("waiting_amount", None),
    ("waiting_amount", "done"):             ("end", None),
    ("waiting_update_data", "done"):        ("end", None),
    ("waiting_editor_source_name", "done"): ("end", None),
}

# state name → message sent when entering this state
_FSM_ENTRY_MESSAGES: dict[str, str] = {
    "waiting_type": replies.registration.type_prompt,
}


# ── Command Registries ────────────────────────────────────────────────

# Available to all DM users
_DM_COMMANDS: dict[str, Callable] = {
    "start": handle_start,
    "menu": handle_menu,
    "sign_doc": handle_sign_doc,
    "update_payment_data": handle_update_payment_data,
    "manage_redirects": handle_manage_redirects,
}

# Admin-only commands (DM)
_ADMIN_COMMANDS: dict[str, Callable] = {
    "generate": cmd_generate,
    "generate_invoices": cmd_generate_invoices,
    "send_global_invoices": cmd_send_global_invoices,
    "send_legium_links": cmd_send_legium_links,
    "orphan_contractors": cmd_orphan_contractors,
    "articles": cmd_articles,
    "lookup": cmd_lookup,
    "budget": cmd_budget,
    "upload_to_airtable": cmd_upload_to_airtable,
    "chatid": cmd_chatid,
    "health": cmd_health,
    "support": cmd_support,
    "code": cmd_code,
    "nl": cmd_nl,
    "teach": cmd_teach,
    "knowledge": cmd_knowledge,
    "ksearch": cmd_ksearch,
    "forget": cmd_forget,
    "kedit": cmd_kedit,
}


# ── Group Chat ────────────────────────────────────────────────────────

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

_GROUP_ALLOWED_COMMANDS = ["menu", "health", "support", "articles", "lookup"]

__all__ = [
    "ContractorStates",
    "_extract_bot_mention",
    "_dispatch_group_command",
    "handle_group_message",
    "_GROUP_COMMAND_HANDLERS",
    "_COMMAND_DESCRIPTIONS",
    "_DM_COMMANDS",
    "_ADMIN_COMMANDS",
    "_FSM_HANDLERS",
    "_FSM_TRANSITIONS",
    "_FSM_ENTRY_MESSAGES",
    "register_all",
    "set_bot_commands",
]


# ── Group Helpers ─────────────────────────────────────────────────────

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
    message: types.Message, state: FSMContext, group_config,
) -> None:
    text = message.text or ""

    # Explicit /command
    if text.startswith("/"):
        raw_cmd = text.split()[0].lstrip("/")
        if "@" in raw_cmd:
            raw_cmd = raw_cmd.split("@", 1)[0]
        if raw_cmd not in group_config.allowed_commands:
            return
        args = text.split(maxsplit=1)
        args_text = args[1] if len(args) > 1 else ""
        await _dispatch_group_command(raw_cmd, args_text, message, state)
        return

    # NL: @mention or reply to bot
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
            from telegram_bot.handlers.conversation_handlers import _handle_nl_reply
            if await _handle_nl_reply(message, state):
                return
        # No command — always RAG reply
        try:
            from backend.domain.services.compose_request import _get_retriever
            from backend.domain.services.conversation_service import generate_nl_reply

            await send_typing(message.chat.id)
            retriever = _get_retriever()
            env_ctx, env_domains = resolve_environment(message.chat.id)
            answer = await asyncio.to_thread(
                generate_nl_reply, clean_text, "", retriever, GeminiGateway(),
                environment=env_ctx, allowed_domains=env_domains,
            )
            sent = await _send_html(message, answer, reply_to_message_id=message.message_id)
            await _save_turn(message, sent, clean_text, answer, {"command": "nl_rag"})
        except Exception:
            logger.exception("RAG reply failed in group chat")
        return

    await _dispatch_group_command(
        result.classified.command, result.classified.args or clean_text, message, state,
    )


# ── FSM Transition Logic ─────────────────────────────────────────────

async def _apply_fsm_transition(
    message: types.Message, state: FSMContext,
    from_state: str, key: str,
) -> None:
    transition = _FSM_TRANSITIONS.get((from_state, key))
    if not transition:
        return
    target, msg_text = transition
    if msg_text:
        await message.answer(msg_text)
    if target == "end":
        await state.clear()
    else:
        target_obj = getattr(ContractorStates, target, None)
        if target_obj:
            await state.set_state(target_obj)
            entry_msg = _FSM_ENTRY_MESSAGES.get(target)
            if entry_msg:
                await message.answer(entry_msg)


async def _route_fsm(
    message: types.Message, state: FSMContext, current_state: str,
) -> None:
    state_name = current_state.split(":")[-1]
    handler = _FSM_HANDLERS.get(state_name)
    if not handler:
        return
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    result = await handler(message, state)
    if result is not None:
        await _apply_fsm_transition(message, state, state_name, result)


# ── Main Router ───────────────────────────────────────────────────────

class _GroupConfig:
    """Module-level editorial group config."""
    allowed_commands = _GROUP_ALLOWED_COMMANDS
    natural_language = True


async def _route_text(message: types.Message, state: FSMContext) -> None:
    text = message.text or ""

    # 1. Group messages
    if message.chat.type in ("group", "supergroup"):
        if EDITORIAL_CHAT_ID and message.chat.id == EDITORIAL_CHAT_ID:
            await handle_group_message(message, state, _GroupConfig)
        return

    # 2. Commands
    if text.startswith("/"):
        raw_cmd = text.split()[0].lstrip("/")
        if "@" in raw_cmd:
            raw_cmd = raw_cmd.split("@", 1)[0]
        if raw_cmd in _DM_COMMANDS:
            await _DM_COMMANDS[raw_cmd](message, state)
            return
        if is_admin(message.from_user.id) and raw_cmd in _ADMIN_COMMANDS:
            await _ADMIN_COMMANDS[raw_cmd](message, state)
        return

    # 3. Admin reply-to-message
    if is_admin(message.from_user.id) and message.reply_to_message:
        await handle_admin_reply(message, state)
        return

    # 4. Active FSM state
    current_state = await state.get_state()
    if current_state is not None:
        await _route_fsm(message, state, current_state)
        return

    # 5. Catch-all: contractor free text
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    result = await handle_contractor_text(message, state)
    if result is not None:
        await _apply_fsm_transition(message, state, "lookup", result)


# ── Registration ──────────────────────────────────────────────────────

async def set_bot_commands(bot) -> None:
    await bot.set_my_commands([
        BotCommand(command="menu", description="Меню"),
    ])


def register_all(dp: Dispatcher) -> None:
    """Wire everything onto the dispatcher — one place to see all handlers."""
    from telegram_bot.handlers.support_handlers import (
        handle_support_callback, handle_editorial_callback, handle_code_rate_callback,
    )

    # Callback queries
    dp.callback_query.register(handle_support_callback, F.data.startswith("support:"))
    dp.callback_query.register(handle_editorial_callback, F.data.startswith("editorial:"))
    dp.callback_query.register(handle_duplicate_callback, F.data.startswith("dup:"))
    dp.callback_query.register(handle_editor_source_callback, F.data.startswith("esrc:"))
    dp.callback_query.register(handle_linked_menu_callback, F.data.startswith("menu:"))
    dp.callback_query.register(handle_code_rate_callback, F.data.startswith("code_rate:"))

    # Single text handler — all routing in _route_text
    dp.message.register(_route_text, F.text)

    # Documents
    dp.message.register(handle_document, F.document)

    # Media (photos, stickers, etc.)
    dp.message.register(
        handle_non_document,
        F.photo | F.sticker | F.video | F.voice | F.video_note | F.audio,
    )
