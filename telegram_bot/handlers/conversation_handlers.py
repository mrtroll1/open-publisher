"""Teaching/knowledge/NL conversation handlers."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

from aiogram import types
from aiogram.fsm.context import FSMContext

from backend.domain.services.compose_request import _get_retriever
from backend.domain.services.command_classifier import CommandClassifier

from backend.domain.services.conversation_service import (
    build_conversation_context,
    format_reply_chain as _format_reply_chain,
    generate_nl_reply,
)
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from telegram_bot import replies
from telegram_bot.bot_helpers import is_admin
from telegram_bot.handler_utils import _db, _kedit_pending, _memory, _save_turn, _send, _send_html, resolve_environment, resolve_entity_context, send_typing

logger = logging.getLogger(__name__)

_TEACHING_KEYWORDS = ("запомни", "учти", "имей в виду", "remember")

# All commands available for admin /nl classification
_ADMIN_NL_DESCRIPTIONS: dict[str, str] = {
    "health": "Проверка доступности сайтов и подов",
    "support": "Любой вопрос о продукте, сайте, функциях, настройках, подписке или техподдержке",
    "articles": "Статьи контрагента за месяц",
    "lookup": "Информация о контрагенте",
    "generate": "Сгенерировать документ для контрагента",
    "generate_invoices": "Сгенерировать счета для всех контрагентов",
    "send_global_invoices": "Отправить глобальные счета контрагентам в Telegram",
    "send_legium_links": "Отправить ссылки на Легиум контрагентам в Telegram",
    "orphan_contractors": "Показать несовпадения между бюджетом и контрагентами",
    "budget": "Расчёт бюджета",
    "code": "Запустить Claude Code для ответов, требующих посмотреть или изменить код",
}

_VALID_ENTITY_KINDS = {"person", "organization", "publication", "product", "competitor"}

__all__ = [
    "cmd_nl",
    "cmd_teach",
    "cmd_knowledge",
    "cmd_ksearch",
    "cmd_forget",
    "cmd_kedit",
    "handle_kedit_reply",
    "cmd_env",
    "cmd_env_edit",
    "cmd_env_bind",
    "cmd_env_create",
    "cmd_env_unbind",
    "cmd_entity",
    "cmd_entity_add",
    "cmd_entity_link",
    "cmd_entity_note",
    "_classify_teaching_text",
    "_format_reply_chain",
    "_handle_nl_reply",
]


async def _handle_nl_reply(message: types.Message, state: FSMContext) -> bool:
    """Handle a conversational NL reply to a bot message. Returns True on success."""
    if await state.get_state() is not None:
        return False

    reply = message.reply_to_message
    if not reply:
        return False

    if not reply.from_user or not reply.from_user.is_bot:
        return False

    try:
        await send_typing(message.chat.id)

        # Detect teaching patterns — classify & store before LLM call, then continue
        user_text_lower = (message.text or "").lower()
        if any(kw in user_text_lower for kw in _TEACHING_KEYWORDS):
            if is_admin(message.from_user.id):
                try:
                    await asyncio.to_thread(_memory.teach, message.text)
                except Exception:
                    logger.exception("Failed to store NL teaching")

        # Build conversation history
        history, parent_id = await asyncio.to_thread(
            build_conversation_context,
            message.chat.id, reply.message_id, reply.text or "", _db,
        )

        # Generate reply via LLM
        retriever = _get_retriever()
        env_ctx, env_domains = await asyncio.to_thread(resolve_environment, message.chat.id)
        user_ctx = await asyncio.to_thread(resolve_entity_context, message.from_user.id)
        answer = await asyncio.to_thread(
            generate_nl_reply,
            message.text, history, retriever, GeminiGateway(),
            environment=env_ctx, allowed_domains=env_domains,
            user_context=user_ctx,
        )

        sent = await _send_html(message, answer, reply_to_message_id=message.message_id)
        await _save_turn(message, sent, message.text, answer, {"command": "nl_reply"},
                         parent_id=parent_id)
        return True
    except Exception:
        logger.exception("NL reply failed")
        return False


async def cmd_nl(message: types.Message, state: FSMContext) -> None:
    """Natural language command classification for admin DM."""
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer("Использование: /nl <текст команды на естественном языке>")
        return

    text = args[1].strip()

    try:
        classifier = CommandClassifier(GeminiGateway())
        result = await asyncio.to_thread(
            classifier.classify, text, _ADMIN_NL_DESCRIPTIONS,
        )
    except Exception:
        logger.exception("NL classification failed")
        await message.answer("Не удалось классифицировать команду.")
        return

    if not result.classified:
        try:
            await send_typing(message.chat.id)
            retriever = _get_retriever()
            env_ctx, env_domains = await asyncio.to_thread(resolve_environment, message.chat.id)
            user_ctx = await asyncio.to_thread(resolve_entity_context, message.from_user.id)
            answer = await asyncio.to_thread(
                generate_nl_reply, text, "", retriever, GeminiGateway(),
                environment=env_ctx, allowed_domains=env_domains,
                user_context=user_ctx,
            )
            sent = await _send_html(message, answer)
            await _save_turn(message, sent, text, answer, {"command": "nl_rag"})
        except Exception:
            logger.exception("RAG reply failed in cmd_nl")
            await message.answer("Не удалось ответить.")
        return

    cmd = result.classified.command
    cmd_args = result.classified.args or text

    # Build the handler map lazily (avoid circular imports)
    from telegram_bot.router import _GROUP_COMMAND_HANDLERS
    from telegram_bot.handlers.admin_handlers import (
        cmd_generate, cmd_generate_invoices, cmd_send_global_invoices,
        cmd_send_legium_links, cmd_orphan_contractors, cmd_budget,
    )
    from telegram_bot.handlers.support_handlers import cmd_code

    handlers: dict[str, Callable] = {
        **_GROUP_COMMAND_HANDLERS,
        "generate": cmd_generate,
        "generate_invoices": cmd_generate_invoices,
        "send_global_invoices": cmd_send_global_invoices,
        "send_legium_links": cmd_send_legium_links,
        "orphan_contractors": cmd_orphan_contractors,
        "budget": cmd_budget,
        "code": cmd_code,
    }

    handler = handlers.get(cmd)
    if not handler:
        await message.answer(f"Команда {cmd} не найдена.")
        return

    # Temporarily rewrite .text (Message is a frozen Pydantic model)
    original_text = message.text
    object.__setattr__(message, "text", f"/{cmd} {cmd_args}" if cmd_args else f"/{cmd}")
    try:
        await handler(message, state)
    finally:
        object.__setattr__(message, "text", original_text)


async def _classify_teaching_text(text: str) -> tuple[str, str]:
    """Classify teaching text into (domain, tier) via MemoryService."""
    return await asyncio.to_thread(_memory.classify_teaching, text)


async def cmd_teach(message: types.Message, state: FSMContext) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer(replies.teach.usage)
        return

    text = args[1].strip()
    try:
        domain, tier = await _classify_teaching_text(text)
        await asyncio.to_thread(_memory.teach, text, domain, tier)
    except Exception:
        logger.exception("Failed to store teaching")
        await message.answer("Не удалось сохранить.")
        return
    await message.answer(replies.teach.stored_fmt.format(domain=domain, tier=tier))


async def cmd_knowledge(message: types.Message, state: FSMContext) -> None:
    parts = message.text.split()[1:]
    verbose = "-v" in parts
    if verbose:
        parts.remove("-v")

    domain = parts[0] if len(parts) >= 1 else None
    tier = parts[1] if len(parts) >= 2 else None

    try:
        entries = await asyncio.to_thread(_memory.list_knowledge, domain=domain, tier=tier)
    except Exception:
        logger.exception("Failed to list knowledge")
        await message.answer("Ошибка при загрузке записей.")
        return

    if not entries:
        await message.answer(replies.knowledge.empty)
        return

    template = replies.knowledge.entry_verbose if verbose else replies.knowledge.entry

    # Group by (tier, domain) for readability
    grouped: dict[tuple[str, str], list[tuple[int, dict]]] = {}
    for i, e in enumerate(entries, 1):
        key = (e["tier"], e["domain"])
        grouped.setdefault(key, []).append((i, e))

    lines = [replies.knowledge.header.format(count=len(entries))]
    for (tier_name, domain_name), items in grouped.items():
        lines.append(f"<b>[{tier_name}] {domain_name}</b>")
        for i, e in items:
            date = e["created_at"].strftime("%Y-%m-%d") if e.get("created_at") else "?"
            content = e.get("content", "")
            if content and len(content) > 120:
                content = content[:120] + "…"
            lines.append(template.format(
                i=i, tier=e["tier"], domain=e["domain"],
                title=e["title"], id=e["id"],
                source=e["source"], date=date,
                content=content,
            ))
        lines.append("")  # blank line between groups

    await _send(message, "\n".join(lines).rstrip(), parse_mode="HTML")


async def cmd_forget(message: types.Message, state: FSMContext) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer(replies.knowledge.forget_usage)
        return

    entry_id = args[1].strip()
    try:
        found = await asyncio.to_thread(_memory.deactivate_entry, entry_id)
    except Exception:
        logger.exception("Failed to deactivate knowledge entry")
        await message.answer(replies.knowledge.not_found)
        return
    if not found:
        await message.answer(replies.knowledge.not_found)
        return
    await message.answer(replies.knowledge.forget_done)


async def cmd_kedit(message: types.Message, state: FSMContext) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer(replies.knowledge.edit_usage)
        return

    entry_id = args[1].strip()
    try:
        entry = await asyncio.to_thread(_memory.get_entry, entry_id)
    except Exception:
        logger.exception("Failed to fetch knowledge entry")
        await message.answer(replies.knowledge.not_found)
        return
    if not entry:
        await message.answer(replies.knowledge.not_found)
        return

    header = f"[{entry['tier']}] {entry['domain']} / {entry['title']}"
    text = f"{header}\n\n```\n{entry['content']}\n```\n\n{replies.knowledge.edit_prompt}"
    sent = await _send_html(message, text)
    _kedit_pending[(message.chat.id, sent.message_id)] = entry_id


async def handle_kedit_reply(message: types.Message) -> bool:
    """Handle a reply to a kedit message. Returns True if handled."""
    reply = message.reply_to_message
    if not reply or not reply.from_user or not reply.from_user.is_bot:
        return False

    key = (message.chat.id, reply.message_id)
    entry_id = _kedit_pending.get(key)
    if not entry_id:
        return False

    del _kedit_pending[key]
    new_content = (message.text or "").strip()
    if not new_content:
        await message.answer(replies.knowledge.edit_usage)
        return True

    try:
        found = await asyncio.to_thread(_memory.update_entry, entry_id, new_content)
    except Exception:
        logger.exception("Failed to edit knowledge entry")
        await message.answer(replies.knowledge.not_found)
        return True
    if not found:
        await message.answer(replies.knowledge.not_found)
        return True
    await message.answer(replies.knowledge.edit_done)
    return True


async def cmd_ksearch(message: types.Message, state: FSMContext) -> None:
    """Semantic search over knowledge entries."""
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer(replies.ksearch.usage)
        return

    query = args[1].strip()
    try:
        results = await asyncio.to_thread(_memory.recall, query, limit=10)
    except Exception:
        logger.exception("Knowledge search failed")
        await message.answer("Ошибка поиска.")
        return

    if not results:
        await message.answer(replies.ksearch.empty)
        return

    lines = [replies.ksearch.header.format(count=len(results), query=query)]
    for i, e in enumerate(results, 1):
        sim = e.get("similarity", 0)
        lines.append(
            f"{i}. {e['title']}  [{e['tier']}] {e['domain']}\n"
            f"   {e['id']}  (сходство: {sim:.2f})"
        )

    await _send(message, "\n".join(lines), parse_mode="HTML")


async def cmd_env(message: types.Message, state: FSMContext) -> None:
    """List environments or show details: /env [name]"""
    args = message.text.split(maxsplit=1)
    name = args[1].strip() if len(args) > 1 and args[1].strip() else None

    if name:
        env = await asyncio.to_thread(_memory.get_environment, name=name)
        if not env:
            await message.answer(replies.env.not_found)
            return
        bindings = await asyncio.to_thread(_db.get_bindings_for_environment, name)
        domains = ", ".join(env["allowed_domains"]) if env.get("allowed_domains") else "—"
        chats = ", ".join(str(c) for c in bindings) if bindings else "—"
        text = (
            f"<b>{env['name']}</b>\n"
            f"Описание: {env['description']}\n"
            f"Домены: {domains}\n"
            f"Чаты: {chats}\n\n"
            f"system_context:\n<pre>{env['system_context']}</pre>"
        )
        await _send(message, text, parse_mode="HTML")
        return

    envs = await asyncio.to_thread(_memory.list_environments)
    if not envs:
        await message.answer(replies.env.empty)
        return

    lines = []
    for e in envs:
        domains = ", ".join(e["allowed_domains"]) if e.get("allowed_domains") else "—"
        bindings = await asyncio.to_thread(_db.get_bindings_for_environment, e["name"])
        chats = ", ".join(str(c) for c in bindings) if bindings else "—"
        lines.append(
            f"<b>{e['name']}</b> — {e['description']}\n"
            f"  домены: {domains}\n"
            f"  чаты: {chats}"
        )
    await _send(message, "\n\n".join(lines), parse_mode="HTML")


async def cmd_env_edit(message: types.Message, state: FSMContext) -> None:
    """Edit environment field: /env_edit <name> <field> <value>"""
    args = message.text.split(maxsplit=3)
    if len(args) < 4:
        await message.answer(replies.env.edit_usage)
        return

    name = args[1].strip()
    field = args[2].strip()
    value = args[3].strip()

    allowed_fields = {"description", "system_context", "allowed_domains"}
    if field not in allowed_fields:
        await message.answer(replies.env.edit_usage)
        return

    if field == "allowed_domains":
        parsed_value = [d.strip() for d in value.split(",") if d.strip()]
    else:
        parsed_value = value

    ok = await asyncio.to_thread(_memory.update_environment, name, **{field: parsed_value})
    if not ok:
        await message.answer(replies.env.update_failed.format(name=name))
        return
    await message.answer(replies.env.updated.format(name=name, field=field))


async def cmd_env_bind(message: types.Message, state: FSMContext) -> None:
    """Bind current chat to environment: /env_bind <name>"""
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer(replies.env.bind_usage)
        return

    name = args[1].strip()
    env = await asyncio.to_thread(_memory.get_environment, name=name)
    if not env:
        await message.answer(replies.env.not_found)
        return

    await asyncio.to_thread(_db.bind_chat, message.chat.id, name)
    await message.answer(replies.env.bound.format(name=name))


async def cmd_env_create(message: types.Message, state: FSMContext) -> None:
    """Create environment: /env_create <name> <description>"""
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer(replies.env.create_usage)
        return
    name = args[1].strip()
    description = args[2].strip()
    await asyncio.to_thread(_db.save_environment, name, description, "")
    await message.answer(replies.env.created.format(name=name))


async def cmd_env_unbind(message: types.Message, state: FSMContext) -> None:
    """Unbind current chat from its environment: /env_unbind"""
    await asyncio.to_thread(_db.unbind_chat, message.chat.id)
    await message.answer(replies.env.unbound)


async def cmd_entity(message: types.Message, state: FSMContext) -> None:
    args = message.text.split(maxsplit=1)
    query = args[1].strip() if len(args) > 1 and args[1].strip() else None

    if query:
        try:
            entities = await asyncio.to_thread(_db.find_entities_by_name, query)
        except Exception:
            logger.exception("Entity search failed")
            await message.answer(replies.entity.not_found)
            return
        if not entities:
            await message.answer(replies.entity.not_found)
            return
        lines = []
        for e in entities:
            ext = e.get("external_ids") or {}
            ext_str = ", ".join(f"{k}={v}" for k, v in ext.items()) if ext else "—"
            lines.append(f"<b>{e['name']}</b> [{e['kind']}]\n  ID: {e['id']}\n  ext: {ext_str}")
        await _send(message, "\n\n".join(lines), parse_mode="HTML")
        return

    try:
        entities = await asyncio.to_thread(_db.list_entities)
    except Exception:
        logger.exception("Entity list failed")
        await message.answer(replies.entity.empty)
        return

    if not entities:
        await message.answer(replies.entity.empty)
        return

    grouped: dict[str, list[dict]] = {}
    for e in entities:
        grouped.setdefault(e["kind"], []).append(e)

    lines = []
    for kind, items in grouped.items():
        lines.append(f"<b>{kind}</b>")
        for e in items:
            lines.append(f"  {e['name']}")
        lines.append("")
    await _send(message, "\n".join(lines).rstrip(), parse_mode="HTML")


async def cmd_entity_add(message: types.Message, state: FSMContext) -> None:
    args = message.text.split(maxsplit=2)
    if len(args) < 3 or not args[2].strip():
        await message.answer(replies.entity.add_usage)
        return

    kind = args[1].strip().lower()
    name = args[2].strip()

    if kind not in _VALID_ENTITY_KINDS:
        await message.answer(replies.entity.invalid_kind)
        return

    try:
        await asyncio.to_thread(_memory.add_entity, kind, name)
    except Exception:
        logger.exception("Entity add failed")
        await message.answer("Не удалось создать сущность.")
        return
    await message.answer(replies.entity.added.format(name=name, kind=kind))


async def cmd_entity_link(message: types.Message, state: FSMContext) -> None:
    args = message.text.split()
    if len(args) < 3:
        await message.answer(replies.entity.link_usage)
        return

    # Last args with = are key=value pairs, everything before is entity name
    kv_pairs = {}
    name_parts = []
    for arg in args[1:]:
        if "=" in arg:
            k, v = arg.split("=", 1)
            kv_pairs[k] = v
        else:
            name_parts.append(arg)

    if not name_parts or not kv_pairs:
        await message.answer(replies.entity.link_usage)
        return

    entity_name = " ".join(name_parts)

    try:
        entity = await asyncio.to_thread(_memory.find_entity, query=entity_name)
    except Exception:
        logger.exception("Entity link search failed")
        await message.answer(replies.entity.not_found)
        return

    if not entity:
        await message.answer(replies.entity.not_found)
        return

    merged = {**(entity.get("external_ids") or {}), **kv_pairs}

    try:
        await asyncio.to_thread(_db.update_entity, entity["id"], external_ids=merged)
    except Exception:
        logger.exception("Entity link update failed")
        await message.answer("Не удалось обновить.")
        return
    await message.answer(replies.entity.linked.format(name=entity["name"]))


async def cmd_entity_note(message: types.Message, state: FSMContext) -> None:
    args = message.text.split(maxsplit=2)
    if len(args) < 3 or not args[2].strip():
        await message.answer(replies.entity.note_usage)
        return

    entity_name = args[1].strip()
    text = args[2].strip()

    try:
        entity = await asyncio.to_thread(_memory.find_entity, query=entity_name)
    except Exception:
        logger.exception("Entity note search failed")
        await message.answer(replies.entity.not_found)
        return

    if not entity:
        await message.answer(replies.entity.not_found)
        return

    try:
        await asyncio.to_thread(
            _memory.remember, text, "general",
            source="admin_teach", entity_id=entity["id"],
        )
    except Exception:
        logger.exception("Entity note store failed")
        await message.answer("Не удалось сохранить заметку.")
        return
    await message.answer(replies.entity.noted.format(name=entity["name"]))
