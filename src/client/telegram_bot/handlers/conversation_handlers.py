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
    "_handle_nl_reply",
    "cmd_env",
    "cmd_env_bind",
    "cmd_env_create",
    "cmd_env_edit",
    "cmd_env_unbind",
    "cmd_forget",
    "cmd_kedit",
    "cmd_knowledge",
    "cmd_ksearch",
    "cmd_nl",
    "cmd_teach",
    "cmd_user",
    "cmd_users",
    "handle_kedit_reply",
]


def _is_reply_to_bot(message: types.Message, _state: FSMContext) -> bool:
    reply = message.reply_to_message
    return bool(reply and reply.from_user and reply.from_user.is_bot)


def _extract_result_fields(result) -> tuple[str, str | None, str | None]:
    if isinstance(result, dict):
        return (result.get("reply", str(result)),
                result.get("parent_id"), result.get("run_id"))
    return str(result), None, None


async def _handle_nl_reply(message: types.Message, state: FSMContext) -> bool:
    if await state.get_state() is not None or not _is_reply_to_bot(message, state):
        return False
    reply = message.reply_to_message
    thinking: ThinkingMessage | None = None
    try:
        thinking, result = await _stream_with_thinking(message, thinking,
            input=message.text, chat_id=message.chat.id,
            reply_to_message_id=reply.message_id, reply_to_text=reply.text or "")
        answer, parent_id, run_id = _extract_result_fields(result)
        sent = await _finish_thinking(thinking, message, answer, reply_to_message_id=message.message_id)
        meta = {"command": "nl_reply"}
        if run_id:
            meta["run_id"] = run_id
        await _save_turn(message, sent, message.text, answer, meta, parent_id=parent_id)
        return True
    except Exception:
        if thinking:
            await thinking.__aexit__(None, None, None)
        logger.exception("NL reply failed")
        await message.answer("Не удалось ответить.")
        return False


async def _stream_with_thinking(message, thinking, **kwargs):
    async def _on_progress(stage: str, detail: str) -> None:
        nonlocal thinking
        text = detail or stage
        if thinking is None:
            thinking = ThinkingMessage(message, text)
            await thinking.__aenter__()
        else:
            await thinking.update(text)

    result = await backend_client.process_stream(
        environment_id=str(message.chat.id),
        user_id=str(message.from_user.id),
        on_progress=_on_progress, **kwargs)
    return thinking, result


async def _finish_thinking(thinking, message, answer, **kwargs):
    if thinking:
        return await thinking.finish_long(answer, **kwargs)
    return await _send_html(message, answer, **kwargs)


async def _send_nl_reply(
    message: types.Message, text: str, result: dict,
    thinking: ThinkingMessage | None,
) -> None:
    """Send a conversational NL reply and save the turn."""
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


async def cmd_nl(message: types.Message, _state: FSMContext) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer("Использование: /nl <текст команды на естественном языке>")
        return
    text = args[1].strip()
    thinking: ThinkingMessage | None = None
    try:
        thinking, result = await _stream_with_thinking(message, thinking, input=text)
    except Exception:
        if thinking:
            await thinking.__aexit__(None, None, None)
        logger.exception("NL processing failed")
        await message.answer("Не удалось обработать команду.")
        return
    await _dispatch_nl_result(message, text, result, thinking)


async def _dispatch_nl_result(message, text, result, thinking):
    if isinstance(result, dict) and "reply" in result:
        await _send_nl_reply(message, text, result, thinking)
        return
    if thinking:
        await thinking.__aexit__(None, None, None)
    text_result = result.get("text", result.get("reply", str(result))) if isinstance(result, dict) else str(result)
    await _send_html(message, text_result)


async def cmd_users(message: types.Message, _state: FSMContext) -> None:
    try:
        users = await backend_client.list_users()
    except Exception:
        logger.exception("Failed to list users")
        await message.answer("Не удалось загрузить список.")
        return
    if not users:
        await message.answer("Пользователей нет.")
        return
    lines = []
    for u in users:
        parts = [f"<b>{u.get('name') or '?'}</b>", u.get("role", "?")]
        if u.get("telegram_id"):
            parts.append(f"tg={u['telegram_id']}")
        if u.get("email"):
            parts.append(u["email"])
        lines.append(" | ".join(parts))
    await message.answer("\n".join(lines), parse_mode="HTML")


async def cmd_user(message: types.Message, _state: FSMContext) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer(
            "Использование: /user &lt;описание&gt;\n"
            "Примеры:\n"
            "<code>/user Маша Иванова, telegram 123456789, редактор</code>\n"
            "<code>/user 123456789 Петя editor</code>",
            parse_mode="HTML",
        )
        return

    text = args[1].strip()
    try:
        result = await backend_client.manage_user(text=text)
    except Exception:
        logger.exception("Failed to manage user")
        await message.answer("Не удалось обработать.")
        return

    if result.get("error"):
        await message.answer(result["error"])
        return
    action = result.get("action", "?")
    user = result.get("user", {})
    await message.answer(
        f"{'Создан' if action == 'created' else 'Обновлён'}: "
        f"<b>{user.get('name', '?')}</b> ({user.get('role', '?')})",
        parse_mode="HTML",
    )


async def cmd_teach(message: types.Message, _state: FSMContext) -> None:
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


def _format_date(date) -> str:
    if hasattr(date, "strftime"):
        return date.strftime("%Y-%m-%d")
    if isinstance(date, str) and len(date) > 10:
        return date[:10]
    return str(date) if date else "?"


def _group_entries(entries: list[dict]) -> dict[tuple[str, str], list[tuple[int, dict]]]:
    grouped: dict[tuple[str, str], list[tuple[int, dict]]] = {}
    for i, e in enumerate(entries, 1):
        grouped.setdefault((e["tier"], e["domain"]), []).append((i, e))
    return grouped


def _format_knowledge_group(tier_name, domain_name, items, template) -> list[str]:
    lines = [f"<b>[{tier_name}] {domain_name}</b>"]
    for i, e in items:
        content = (e.get("content", "") or "")[:120]
        if len(e.get("content", "")) > 120:
            content += "…"
        lines.append(template.format(
            i=i, tier=e["tier"], domain=e["domain"],
            title=e["title"], id=e["id"],
            source=e["source"], date=_format_date(e.get("created_at", "?")),
            content=content,
        ))
    lines.append("")
    return lines


async def cmd_knowledge(message: types.Message, _state: FSMContext) -> None:
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
    lines = [replies.knowledge.header.format(count=len(entries))]
    for (t, d), items in _group_entries(entries).items():
        lines.extend(_format_knowledge_group(t, d, items, template))
    await _send(message, "\n".join(lines).rstrip(), parse_mode="HTML")


async def cmd_forget(message: types.Message, _state: FSMContext) -> None:
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


async def cmd_kedit(message: types.Message, _state: FSMContext) -> None:
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


async def cmd_ksearch(message: types.Message, _state: FSMContext) -> None:
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


def _format_chats(bindings: list) -> str:
    return ", ".join(str(c) for c in bindings) if bindings else "—"


async def _show_env_detail(message, name):
    env = await backend_client.get_environment(name=name)
    if not env:
        await message.answer(replies.env.not_found)
        return
    bindings = await backend_client.get_bindings(name)
    text = (
        f"<b>{env['name']}</b>\n"
        f"Описание: {env['description']}\n"
        f"Чаты: {_format_chats(bindings)}\n\n"
        f"system_context:\n<pre>{env['system_context']}</pre>"
    )
    await _send(message, text, parse_mode="HTML")


async def _show_env_list(message):
    envs = await backend_client.list_environments()
    if not envs:
        await message.answer(replies.env.empty)
        return
    lines = []
    for e in envs:
        bindings = await backend_client.get_bindings(e["name"])
        lines.append(
            f"<b>{e['name']}</b> — {e['description']}\n"
            f"  чаты: {_format_chats(bindings)}"
        )
    await _send(message, "\n\n".join(lines), parse_mode="HTML")


async def cmd_env(message: types.Message, _state: FSMContext) -> None:
    args = message.text.split(maxsplit=1)
    name = args[1].strip() if len(args) > 1 and args[1].strip() else None
    if name:
        await _show_env_detail(message, name)
    else:
        await _show_env_list(message)


_ENV_EDITABLE_FIELDS = {"description", "system_context", "telegram_handle"}


def _parse_env_value(value: str):
    return value


async def cmd_env_edit(message: types.Message, _state: FSMContext) -> None:
    args = message.text.split(maxsplit=3)
    if len(args) < 4 or args[2].strip() not in _ENV_EDITABLE_FIELDS:
        await message.answer(replies.env.edit_usage)
        return
    name, field, value = args[1].strip(), args[2].strip(), args[3].strip()
    ok = await backend_client.update_environment(name, **{field: _parse_env_value(value)})
    if not ok:
        await message.answer(replies.env.update_failed.format(name=name))
        return
    await message.answer(replies.env.updated.format(name=name, field=field))


async def cmd_env_bind(message: types.Message, _state: FSMContext) -> None:
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


async def cmd_env_create(message: types.Message, _state: FSMContext) -> None:
    """Create environment: /env_create <name> <description>"""
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer(replies.env.create_usage)
        return
    name = args[1].strip()
    description = args[2].strip()
    await backend_client.create_environment(name, description)
    await message.answer(replies.env.created.format(name=name))


async def cmd_env_unbind(message: types.Message, _state: FSMContext) -> None:
    """Unbind current chat from its environment: /env_unbind"""
    await backend_client.unbind_environment(message.chat.id)
    await message.answer(replies.env.unbound)


async def cmd_perm(message: types.Message, _state: FSMContext) -> None:
    """/perm [tool] — list permissions, optionally filtered by tool name."""
    args = message.text.split(maxsplit=1)
    filter_tool = args[1].strip() if len(args) > 1 else None
    perms = await backend_client.list_permissions()
    if filter_tool:
        perms = [p for p in perms if p["tool_name"] == filter_tool]
    if not perms:
        await message.answer("Нет настроенных разрешений." if not filter_tool else f"Нет разрешений для {filter_tool}.")
        return
    by_tool: dict[str, list[str]] = {}
    for p in perms:
        by_tool.setdefault(p["tool_name"], []).append(
            f"  {p['environment']}: {', '.join(p['allowed_roles'])}"
        )
    lines = []
    for tool_name, entries in by_tool.items():
        lines.append(f"<b>{tool_name}</b>\n" + "\n".join(entries))
    await _send(message, "\n\n".join(lines), parse_mode="HTML")
