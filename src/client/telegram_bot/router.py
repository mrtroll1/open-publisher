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

import logging
from collections.abc import Callable

from aiogram import Dispatcher, F, types
from aiogram.enums import ChatAction
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BotCommand

from telegram_bot import backend_client
from telegram_bot.bot_helpers import is_admin
from telegram_bot.config import BOT_USERNAME
from telegram_bot.handler_utils import ThinkingMessage, _save_turn, _send_html, resolve_environment_record
from telegram_bot.handlers.admin_handlers import (
    cmd_articles,
    cmd_budget,
    cmd_chatid,
    cmd_extract_knowledge,
    cmd_generate,
    cmd_generate_invoices,
    cmd_ingest_articles,
    cmd_lookup,
    cmd_orphan_contractors,
    cmd_send_global_invoices,
    cmd_send_legium_links,
    cmd_upload_to_airtable,
    handle_admin_reply,
)
from telegram_bot.handlers.contractor_handlers import (
    handle_amount_input,
    handle_contractor_text,
    handle_data_input,
    handle_document,
    handle_duplicate_callback,
    handle_editor_source_callback,
    handle_editor_source_name,
    handle_linked_menu_callback,
    handle_manage_redirects,
    handle_menu,
    handle_non_document,
    handle_sign_doc,
    handle_start,
    handle_type_selection,
    handle_update_data,
    handle_update_payment_data,
    handle_verification_code,
)
from telegram_bot.handlers.conversation_handlers import (
    cmd_env,
    cmd_env_bind,
    cmd_env_create,
    cmd_env_edit,
    cmd_env_unbind,
    cmd_forget,
    cmd_kedit,
    cmd_knowledge,
    cmd_ksearch,
    cmd_nl,
    cmd_teach,
)
from telegram_bot.handlers.support_handlers import (
    cmd_code,
    cmd_health,
    cmd_support,
    handle_code_rate_callback,
    handle_editorial_callback,
    handle_support_callback,
)

logger = logging.getLogger(__name__)

# Commands where original user text should be passed as-is (LLM processes it)
_LLM_COMMANDS = {"code", "support"}


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
    "ingest_articles": cmd_ingest_articles,
    "extract_knowledge": cmd_extract_knowledge,
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
    "env": cmd_env,
    "env_edit": cmd_env_edit,
    "env_bind": cmd_env_bind,
    "env_create": cmd_env_create,
    "env_unbind": cmd_env_unbind,
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
    "lookup": "Информация о контрагенте (автор/редактор/корректор/...)",
}

_GROUP_ALLOWED_COMMANDS = ["health", "support", "articles", "lookup"]

__all__ = [
    "_ADMIN_COMMANDS",
    "_COMMAND_DESCRIPTIONS",
    "_DM_COMMANDS",
    "_FSM_HANDLERS",
    "_GROUP_COMMAND_HANDLERS",
    "ContractorStates",
    "_dispatch_group_command",
    "_extract_bot_mention",
    "handle_group_message",
    "register_all",
    "set_bot_commands",
]


# ── Group Helpers ─────────────────────────────────────────────────────

def _extract_bot_mention(text: str, bot_username: str) -> str | None:
    prefix = f"@{bot_username}"
    if text.startswith((prefix + " ", prefix + "\n")):
        return text[len(prefix):].strip()
    return None


async def _dispatch_group_command(
    command: str, args_text: str, message: types.Message, state: FSMContext,
) -> None:
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

    if text.startswith("/"):
        await _handle_group_command(text, message, state, group_config)
        return

    if group_config.natural_language:
        await _handle_group_nl(text, message, state)


async def _handle_group_command(
    text: str, message: types.Message, state: FSMContext, group_config,
) -> None:
    raw_cmd = text.split(maxsplit=1)[0].lstrip("/")
    if "@" in raw_cmd:
        raw_cmd = raw_cmd.split("@", 1)[0]
    if raw_cmd not in group_config.allowed_commands:
        return
    args = text.split(maxsplit=1)
    args_text = args[1] if len(args) > 1 else ""
    await _dispatch_group_command(raw_cmd, args_text, message, state)


def _is_group_reply_to_bot(message: types.Message) -> bool:
    return bool(message.reply_to_message
                and message.reply_to_message.from_user
                and message.reply_to_message.from_user.is_bot)


def _resolve_group_text(text: str, message: types.Message) -> str | None:
    clean = _extract_bot_mention(text, BOT_USERNAME)
    if clean is not None:
        return clean
    if _is_group_reply_to_bot(message):
        return text
    return None


async def _handle_group_nl(
    text: str, message: types.Message, _state: FSMContext,
) -> None:
    clean_text = _resolve_group_text(text, message)
    if clean_text is None:
        return
    is_reply = _is_group_reply_to_bot(message)
    kwargs = _build_nl_kwargs(clean_text, message, is_reply_to_bot=is_reply)
    thinking: ThinkingMessage | None = None

    async def _on_progress(stage: str, detail: str) -> None:
        nonlocal thinking
        txt = detail or stage
        if thinking is None:
            thinking = ThinkingMessage(message, txt)
            await thinking.__aenter__()
        else:
            await thinking.update(txt)

    kwargs["on_progress"] = _on_progress
    try:
        result = await backend_client.process_stream(**kwargs)
        await _send_group_result(message, clean_text, result, thinking)
    except Exception:
        if thinking:
            await thinking.__aexit__(None, None, None)
        logger.exception("Group NL processing failed")
        await message.answer("Не удалось обработать сообщение.")


async def _send_group_result(message, clean_text, result, thinking):
    answer = result.get("reply", str(result)) if isinstance(result, dict) else str(result)
    parent_id = result.get("parent_id") if isinstance(result, dict) else None
    run_id = result.get("run_id") if isinstance(result, dict) else None
    if thinking:
        sent = await thinking.finish_long(answer, reply_to_message_id=message.message_id)
    else:
        sent = await _send_html(message, answer, reply_to_message_id=message.message_id)
    meta = {"command": "nl_group"}
    if run_id:
        meta["run_id"] = run_id
    await _save_turn(message, sent, clean_text, answer, meta, parent_id=parent_id)


def _build_nl_kwargs(clean_text: str, message: types.Message, *, is_reply_to_bot: bool) -> dict:
    kwargs = {
        "input": clean_text,
        "environment_id": str(message.chat.id),
        "user_id": str(message.from_user.id),
    }
    if is_reply_to_bot and message.reply_to_message:
        kwargs["chat_id"] = message.chat.id
        kwargs["reply_to_message_id"] = message.reply_to_message.message_id
        kwargs["reply_to_text"] = message.reply_to_message.text or ""
    return kwargs


# ── FSM Routing ──────────────────────────────────────────────────────

async def _route_fsm(
    message: types.Message, state: FSMContext, current_state: str,
) -> None:
    state_name = current_state.rsplit(":", maxsplit=1)[-1]
    handler = _FSM_HANDLERS.get(state_name)
    if not handler:
        return
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    await handler(message, state)


# ── Main Router ───────────────────────────────────────────────────────

class _GroupConfig:
    """Module-level editorial group config."""
    allowed_commands = _GROUP_ALLOWED_COMMANDS
    natural_language = True


_GROUP_ADMIN_COMMANDS = {"env_bind", "env_unbind"}


def _parse_command(text: str) -> str:
    raw_cmd = text.split(maxsplit=1)[0].lstrip("/")
    return raw_cmd.split("@", 1)[0] if "@" in raw_cmd else raw_cmd


async def _route_group(message: types.Message, state: FSMContext) -> None:
    text = message.text or ""
    if text.startswith("/"):
        cmd = _parse_command(text)
        if cmd in _GROUP_ADMIN_COMMANDS and is_admin(message.from_user.id):
            handler = _ADMIN_COMMANDS.get(cmd)
            if handler:
                await handler(message, state)
            return
    env = await resolve_environment_record(message.chat.id)
    if env:
        await handle_group_message(message, state, _GroupConfig)


async def _route_dm_command(message: types.Message, state: FSMContext) -> None:
    cmd = _parse_command(message.text)
    if cmd in _DM_COMMANDS:
        await _DM_COMMANDS[cmd](message, state)
        return
    if is_admin(message.from_user.id) and cmd in _ADMIN_COMMANDS:
        await _ADMIN_COMMANDS[cmd](message, state)


async def _route_text(message: types.Message, state: FSMContext) -> None:
    text = message.text or ""
    if message.chat.type in ("group", "supergroup"):
        await _route_group(message, state)
        return
    if text.startswith("/"):
        await _route_dm_command(message, state)
        return
    if is_admin(message.from_user.id) and message.reply_to_message:
        await handle_admin_reply(message, state)
        return
    current_state = await state.get_state()
    if current_state is not None:
        await _route_fsm(message, state, current_state)
        return
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    await handle_contractor_text(message, state)


# ── Registration ──────────────────────────────────────────────────────

async def set_bot_commands(bot) -> None:
    await bot.set_my_commands([
        BotCommand(command="menu", description="Меню"),
    ])


def register_all(dp: Dispatcher) -> None:
    """Wire everything onto the dispatcher — one place to see all handlers."""
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
