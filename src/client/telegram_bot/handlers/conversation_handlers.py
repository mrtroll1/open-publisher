"""Teaching/knowledge/NL conversation handlers."""

from __future__ import annotations

import logging

from aiogram import types
from aiogram.fsm.context import FSMContext

from telegram_bot import backend_client, replies
from telegram_bot.handler_utils import ThinkingMessage, _kedit_pending, _save_turn, _send, _send_html

logger = logging.getLogger(__name__)

# All commands available for admin /nl classification
_ADMIN_NL_DESCRIPTIONS: dict[str, str] = {
    "health": "Проверка доступности сайтов и подов",
    "support": "Любой вопрос о продукте, сайте, функциях, настройках, подписке или техподдержке",
    "articles": "Статьи контрагента за месяц",
    "lookup": "Информация о контрагенте (автор/редактор/корректор/...)",
    "generate": "Сгенерировать документ для контрагента",
    "generate_invoices": "Сгенерировать счета для всех контрагентов",
    "send_global_invoices": "Отправить глобальные счета контрагентам в Telegram",
    "send_legium_links": "Отправить ссылки на Легиум контрагентам в Telegram",
    "orphan_contractors": "Показать несовпадения между бюджетом и контрагентами",
    "budget": "Расчёт бюджета",
    "code": "Запустить Claude Code для ответов, требующих посмотреть или изменить код",
}

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
        thinking: ThinkingMessage | None = None

        async def _on_progress(stage: str, detail: str) -> None:
            nonlocal thinking
            text = detail or stage
            if thinking is None:
                thinking = ThinkingMessage(message, text)
                await thinking.__aenter__()
            else:
                await thinking.update(text)

        result = await backend_client.process_stream(
            input=message.text,
            environment_id=str(message.chat.id),
            user_id=str(message.from_user.id),
            chat_id=message.chat.id,
            reply_to_message_id=reply.message_id,
            reply_to_text=reply.text or "",
            on_progress=_on_progress,
        )
        answer = result.get("reply", str(result)) if isinstance(result, dict) else str(result)
        parent_id = result.get("parent_id") if isinstance(result, dict) else None
        run_id = result.get("run_id") if isinstance(result, dict) else None

        if thinking:
            sent = await thinking.finish_long(answer, reply_to_message_id=message.message_id)
        else:
            sent = await _send_html(message, answer, reply_to_message_id=message.message_id)
        meta = {"command": "nl_reply"}
        if run_id:
            meta["run_id"] = run_id
        await _save_turn(message, sent, message.text, answer, meta,
                         parent_id=parent_id)
        return True
    except Exception:
        if thinking:
            await thinking.__aexit__(None, None, None)
        logger.exception("NL reply failed")
        return False


async def cmd_nl(message: types.Message, state: FSMContext) -> None:
    """Natural language command classification for admin DM."""
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer("Использование: /nl <текст команды на естественном языке>")
        return

    text = args[1].strip()

    # Let Brain handle classification + routing
    thinking: ThinkingMessage | None = None

    async def _on_progress(stage: str, detail: str) -> None:
        nonlocal thinking
        txt = detail or stage
        if thinking is None:
            thinking = ThinkingMessage(message, txt)
            await thinking.__aenter__()
        else:
            await thinking.update(txt)

    try:
        result = await backend_client.process_stream(
            input=text,
            environment_id=str(message.chat.id),
            user_id=str(message.from_user.id),
            on_progress=_on_progress,
        )
    except Exception:
        if thinking:
            await thinking.__aexit__(None, None, None)
        logger.exception("NL processing failed")
        await message.answer("Не удалось обработать команду.")
        return

    # Brain returns a dict with "reply" for conversation, or command-specific result
    if isinstance(result, dict) and "reply" in result:
        try:
            if thinking:
                sent = await thinking.finish_long(result["reply"])
            else:
                sent = await _send_html(message, result["reply"])
            meta = {"command": "nl_rag"}
            if result.get("run_id"):
                meta["run_id"] = result["run_id"]
            await _save_turn(message, sent, text, result["reply"], meta)
        except Exception:
            logger.exception("Failed to send NL reply")
            await message.answer("Не удалось ответить.")
        return

    if thinking:
        await thinking.__aexit__(None, None, None)

    # If Brain routed to a command, the result is already the command output
    if isinstance(result, dict):
        text_result = result.get("text", result.get("reply", str(result)))
    else:
        text_result = str(result)
    await _send_html(message, text_result)


async def cmd_teach(message: types.Message, state: FSMContext) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer(replies.teach.usage)
        return

    text = args[1].strip()
    try:
        result = await backend_client.teach(text)
    except Exception:
        logger.exception("Failed to store teaching")
        await message.answer("Не удалось сохранить.")
        return
    confirmation = result.get("confirmation", "Запомнил!")
    domain = result.get("domain", "?")
    tier = result.get("tier", "?")
    await message.answer(f"{confirmation}\n\n<code>[{tier}] {domain}</code>", parse_mode="HTML")


async def cmd_knowledge(message: types.Message, state: FSMContext) -> None:
    parts = message.text.split()[1:]
    verbose = "-v" in parts
    if verbose:
        parts.remove("-v")

    domain = parts[0] if len(parts) >= 1 else None
    tier = parts[1] if len(parts) >= 2 else None

    try:
        entries = await backend_client.memory_list(domain=domain, tier=tier)
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
            date = e.get("created_at", "?")
            if hasattr(date, "strftime"):
                date = date.strftime("%Y-%m-%d")
            elif isinstance(date, str) and len(date) > 10:
                date = date[:10]
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
        found = await backend_client.delete_entry(entry_id)
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
        entry = await backend_client.get_entry(entry_id)
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
        found = await backend_client.update_entry(entry_id, new_content)
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
        results = await backend_client.memory_search(query)
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
        env = await backend_client.get_environment(name=name)
        if not env:
            await message.answer(replies.env.not_found)
            return
        bindings = await backend_client.get_bindings(name)
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

    envs = await backend_client.list_environments()
    if not envs:
        await message.answer(replies.env.empty)
        return

    lines = []
    for e in envs:
        domains = ", ".join(e["allowed_domains"]) if e.get("allowed_domains") else "—"
        bindings = await backend_client.get_bindings(e["name"])
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

    ok = await backend_client.update_environment(name, **{field: parsed_value})
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
    env = await backend_client.get_environment(name=name)
    if not env:
        await message.answer(replies.env.not_found)
        return

    await backend_client.bind_environment(message.chat.id, name)
    await message.answer(replies.env.bound.format(name=name))


async def cmd_env_create(message: types.Message, state: FSMContext) -> None:
    """Create environment: /env_create <name> <description>"""
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer(replies.env.create_usage)
        return
    name = args[1].strip()
    description = args[2].strip()
    await backend_client.create_environment(name, description)
    await message.answer(replies.env.created.format(name=name))


async def cmd_env_unbind(message: types.Message, state: FSMContext) -> None:
    """Unbind current chat from its environment: /env_unbind"""
    await backend_client.unbind_environment(message.chat.id)
    await message.answer(replies.env.unbound)
