"""Context building for conversation turns."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from backend.brain.tool import Tool
from backend.config import REPUBLIC_SITE_URL
from backend.infrastructure.repositories.postgres import DbGateway

logger = logging.getLogger(__name__)


def _parse_meta(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _format_chain_entry(entry: dict) -> str:
    meta = _parse_meta(entry.get("metadata"))
    prefix = entry["type"]
    if meta:
        prefix += f" [{' '.join(f'{k}={v}' for k, v in meta.items())}]"
    return f"{prefix}: {entry['text']}"


def _format_reply_chain(chain: list[dict]) -> str:
    return "\n".join(_format_chain_entry(e) for e in chain)


def _truncate_chain(chain: list[dict], max_verbatim: int) -> str:
    if len(chain) <= max_verbatim:
        return _format_reply_chain(chain)
    skipped = len(chain) - max_verbatim
    return f"[{skipped} предыдущих сообщений опущено]\n" + _format_reply_chain(chain[-max_verbatim:])


def build_conversation_context(
    chat_id: int, reply_message_id: int, reply_text: str,
    db: DbGateway, max_verbatim: int = 8,
) -> tuple[str, str | None]:
    msg = db.get_by_telegram_message_id(chat_id, reply_message_id)
    if not msg:
        return f"assistant: {reply_text}", None
    chain = db.get_reply_chain(msg["id"], depth=20)
    return _truncate_chain(chain, max_verbatim), msg["id"]


_BASE_INSTRUCTIONS = [
    "Ты — Иван Добровольский, издатель Republic ({site}). Ведёшь диалог в Telegram.",
    "Используй контекст и инструменты. Отвечай по-русски.",
    "Если не знаешь ответа — скажи.",
    "Отвечай кратко и по делу.",
    "ФОРМАТ: Telegram. ЗАПРЕЩЕНО: markdown-таблицы (|---|), republic.ru. Для списков данных — нумерованный список. Ссылки на статьи: {site}/posts/<id>.",
    "НИКОГДА не выдумывай данные. Если инструмент не вернул результат (ошибка, пустой ответ, 'LLM did not produce a query') — сообщи об этом пользователю, но НЕ придумывай заголовки, названия, цифры или другие данные.",
    "Если спрашивают о твоих прошлых действиях — используй agent_db для поиска в run_logs по run_id из истории. НИКОГДА не выдумывай SQL-запросы или результаты.",
]


def _optional_section(title: str, content: str) -> str:
    return f"\n## {title}\n{content}" if content else ""


_DM_ROLE_CONTEXT = {
    "admin": (
        "Это приватный чат с администратором. Полный доступ ко всем функциям. "
        "Можно обсуждать внутренние вопросы, контрагентов, бюджет. Давай развёрнутые ответы."
    ),
    "editor": (
        "Это личный чат с редактором. Помогай с управлением документами для выплат, "
        "контрагентами, редиректами, ставками. Отвечай по-русски, кратко."
    ),
    "user": "Это личный чат. Будь вежлив. Отвечай по-русски, кратко.",
}


def build_system_prompt(env: dict, user_context: str, knowledge: str,
                        conversation_history: str, goals_summary: str = "") -> str:
    now = datetime.now(timezone(timedelta(hours=1)))
    parts = [f"Текущая дата и время: {now.strftime('%Y-%m-%d %H:%M')} (CET)"]
    parts.extend(line.format(site=REPUBLIC_SITE_URL) for line in _BASE_INSTRUCTIONS)
    env_context = env.get("system_context", "")
    if not env_context:
        env_context = _DM_ROLE_CONTEXT.get(env.get("role", ""), "")
    parts.append(_optional_section("Окружение", env_context))
    parts.append(_optional_section("О собеседнике", user_context))
    parts.append(_optional_section("Контекст", knowledge))
    parts.append(_optional_section("Мои цели и задачи", goals_summary))
    parts.append(_optional_section("История разговора", conversation_history))
    return "\n".join(p for p in parts if p)


def tool_declarations(tools: list[Tool]) -> list[dict]:
    """Convert Tool list to Gemini function declarations."""
    return [
        {"name": t.name, "description": t.description, "parameters": t.parameters}
        for t in tools
    ]
