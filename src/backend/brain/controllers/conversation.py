"""Conversation controller — ReAct loop with Gemini function calling."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from google.genai import types

from backend.brain.authorizer import AuthContext
from backend.brain.tool import Tool
from backend.config import GEMINI_MODEL_SMART, REPUBLIC_SITE_URL
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from backend.infrastructure.memory.retriever import KnowledgeRetriever
from backend.infrastructure.repositories.postgres import DbGateway

logger = logging.getLogger(__name__)

MAX_TOOL_STEPS = 5


def _format_reply_chain(chain: list[dict]) -> str:
    parts = []
    for entry in chain:
        meta = entry.get("metadata") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (json.JSONDecodeError, TypeError):
                meta = {}
        prefix = f"{entry['type']}"
        if meta:
            meta_str = " ".join(f"{k}={v}" for k, v in meta.items())
            prefix += f" [{meta_str}]"
        parts.append(f"{prefix}: {entry['text']}")
    return "\n".join(parts)


def _build_conversation_context(
    chat_id: int, reply_message_id: int, reply_text: str,
    db: DbGateway, max_verbatim: int = 8,
) -> tuple[str, str | None]:
    msg = db.get_by_telegram_message_id(chat_id, reply_message_id)
    if msg:
        chain = db.get_reply_chain(msg["id"], depth=20)
        if len(chain) > max_verbatim:
            skipped = len(chain) - max_verbatim
            chain = chain[-max_verbatim:]
            history = f"[{skipped} предыдущих сообщений опущено]\n" + _format_reply_chain(chain)
        else:
            history = _format_reply_chain(chain)
        return history, msg["id"]
    return f"assistant: {reply_text}", None


def _build_system_prompt(env: dict, user_context: str, knowledge: str,
                         conversation_history: str) -> str:
    now = datetime.now(timezone(timedelta(hours=1)))
    parts = [
        f"Текущая дата и время: {now.strftime('%Y-%m-%d %H:%M')} (CET)",
        f"Ты — Иван Добровольский, издатель Republic ({REPUBLIC_SITE_URL}). Ведёшь диалог в Telegram.",
        "Используй контекст и инструменты. Отвечай по-русски.",
        "Если не знаешь ответа — скажи.",
        "Отвечай кратко и по делу.",
        f"ФОРМАТ: Telegram. ЗАПРЕЩЕНО: markdown-таблицы (|---|), republic.ru. Для списков данных — нумерованный список. Ссылки на статьи: {REPUBLIC_SITE_URL}/posts/<id>.",
        "НИКОГДА не выдумывай данные. Если инструмент не вернул результат (ошибка, пустой ответ, 'LLM did not produce a query') — сообщи об этом пользователю, но НЕ придумывай заголовки, названия, цифры или другие данные. Используй ТОЛЬКО те данные, которые вернули инструменты.",
        "Если спрашивают о твоих прошлых действиях, запросах или результатах — используй agent_db для поиска в run_logs по run_id из истории. НИКОГДА не выдумывай SQL-запросы или результаты — только цитируй из run_logs.",
    ]
    environment = env.get("system_context", "")
    if environment:
        parts.append(f"\n## Окружение\n{environment}")
    if user_context:
        parts.append(f"\n## О собеседнике\n{user_context}")
    if knowledge:
        parts.append(f"\n## Контекст\n{knowledge}")
    if conversation_history:
        parts.append(f"\n## История разговора\n{conversation_history}")
    return "\n".join(parts)


def _tool_declarations(tools: list[Tool]) -> list[dict]:
    """Convert Tool list to Gemini function declarations."""
    return [
        {"name": t.name, "description": t.description, "parameters": t.parameters}
        for t in tools
    ]


def _truncate(obj, max_len=500) -> Any:
    """Truncate long strings in dicts for logging."""
    if isinstance(obj, str):
        return obj[:max_len] + "…" if len(obj) > max_len else obj
    if isinstance(obj, dict):
        return {k: _truncate(v, max_len) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_truncate(v, max_len) for v in obj]
    return obj


def _execute_tool_calls(tool_calls, tools_by_name, auth_ctx, failed_tools, _log):
    """Run each tool call, track failures, return results list."""
    results = []
    for tc in tool_calls:
        _log("tool_call", {"tool": tc["name"], "args": _truncate(tc["args"])})
        tool = tools_by_name.get(tc["name"])
        if not tool:
            results.append({"name": tc["name"], "result": {"error": f"Unknown tool: {tc['name']}"}})
            _log("tool_error", {"tool": tc["name"], "error": "unknown tool"})
            continue
        try:
            result = tool.execute(tc["args"], auth_ctx)
            if isinstance(result, dict) and result.get("error"):
                failed_tools[tc["name"]] = failed_tools.get(tc["name"], 0) + 1
            results.append({"name": tc["name"], "result": result})
            _log("tool_result", {"tool": tc["name"], "result": _truncate(result)})
        except Exception as e:
            logger.warning("Tool %s failed: %s", tc["name"], e, exc_info=True)
            failed_tools[tc["name"]] = failed_tools.get(tc["name"], 0) + 1
            results.append({"name": tc["name"], "result": {"error": str(e)}})
            _log("tool_error", {"tool": tc["name"], "error": str(e)})
    return results


def _has_repeated_failures(failed_tools) -> bool:
    return any(c >= 2 for c in failed_tools.values())


def conversation_handler(
    gemini: GeminiGateway, db: DbGateway, retriever: KnowledgeRetriever,
) -> callable:
    """Create the conversation handler function used by Brain."""

    def handle(input: str, auth: AuthContext, **kwargs) -> dict:
        ctx = _ConversationContext(gemini, db, retriever, input, auth, **kwargs)
        ctx.load_history()
        ctx.load_knowledge()
        system_prompt = _build_system_prompt(auth.ctx.env, ctx.user_context, ctx.knowledge, ctx.history)
        conv_tools = [t for t in auth.tools if t.conversational]
        ctx.log("input", {
            "user_input": input,
            "environment": auth.ctx.env.get("name", ""),
            "tools": [t.name for t in conv_tools],
            "has_history": bool(ctx.history),
        })
        if not conv_tools:
            return ctx.single_llm_call(system_prompt)
        return ctx.react_loop(system_prompt, conv_tools)

    return handle


class _ConversationContext:
    """Holds state for a single conversation turn."""

    def __init__(self, gemini, db, retriever, input, auth, **kwargs):
        self.gemini = gemini
        self.db = db
        self.retriever = retriever
        self.input = input
        self.auth = auth
        self.progress = kwargs.get("progress")
        self.chat_id = kwargs.get("chat_id")
        self.reply_to_message_id = kwargs.get("reply_to_message_id")
        self.reply_to_text = kwargs.get("reply_to_text", "")
        self.run_id = str(uuid.uuid4())
        self._step = 0
        self.history = ""
        self.parent_id = None
        self.user_context = ""
        self.knowledge = ""

    def log(self, type: str, content: dict):
        self.db.log_run_step(self.run_id, self._step, type, content)
        self._step += 1

    def _emit(self, stage: str, detail: str):
        if self.progress:
            self.progress.emit(stage, detail)

    def _reply(self, text: str) -> dict:
        self.log("llm_reply", {"reply": _truncate(text)})
        return {"reply": text, "parent_id": self.parent_id, "run_id": self.run_id}

    def load_history(self):
        self._emit("context", "Загружаю контекст")
        if self.chat_id and self.reply_to_message_id:
            self.history, self.parent_id = _build_conversation_context(
                self.chat_id, self.reply_to_message_id, self.reply_to_text, self.db,
            )

    def load_knowledge(self):
        user = self.auth.ctx.user
        if user and user.get("id"):
            self.user_context = self.retriever.get_user_context(user["id"])
        env = self.auth.ctx.env
        allowed_domains = env.get("allowed_domains")
        if allowed_domains is not None:
            core = self.retriever.get_multi_domain_context(allowed_domains)
            relevant = self.retriever.retrieve(self.input, domains=allowed_domains)
        else:
            core = self.retriever.get_core()
            relevant = self.retriever.retrieve(self.input)
        self.knowledge = (core + "\n\n" + relevant) if core else relevant

    def single_llm_call(self, system_prompt: str) -> dict:
        self._emit("llm", "Генерирую ответ")
        prompt = system_prompt + f"\n\n## Сообщение\n{self.input}\n\nВерни JSON: {{\"reply\": \"<ответ>\"}}"
        result = self.gemini.call(prompt, GEMINI_MODEL_SMART)
        reply = result.get("reply") or result.get("raw_parsed") or "Не удалось сформировать ответ."
        return self._reply(reply)

    def react_loop(self, system_prompt: str, conv_tools: list[Tool]) -> dict:
        declarations = _tool_declarations(conv_tools)
        tools_by_name = {t.name: t for t in conv_tools}

        self._emit("llm", "Думаю...")
        text, tool_calls, resp_content = self.gemini.call_with_tools(
            system_prompt, self.input, declarations, model=GEMINI_MODEL_SMART,
        )
        turn_history = self._init_turn_history(resp_content)
        failed_tools: dict[str, int] = {}

        for iteration in range(MAX_TOOL_STEPS):
            if text:
                return self._reply(text)
            if not tool_calls:
                return self._reply("Не удалось сформировать ответ.")

            self._emit("tool", ", ".join(tc["name"] for tc in tool_calls))
            results = _execute_tool_calls(tool_calls, tools_by_name, self.auth.ctx, failed_tools, self.log)

            if _has_repeated_failures(failed_tools):
                self._log_repeated_failures(failed_tools)
                break

            text, tool_calls, resp_content = self._continue_loop(
                turn_history, results, declarations, iteration,
            )
            self._append_turn(turn_history, results, resp_content)

        return self._reply(text or "Превышен лимит шагов.")

    def _init_turn_history(self, resp_content):
        history = [types.Content(role="user", parts=[types.Part.from_text(text=self.input)])]
        if resp_content:
            history.append(resp_content)
        return history

    def _continue_loop(self, turn_history, results, declarations, iteration):
        self._emit("llm", f"Думаю... (шаг {iteration + 2})")
        is_last_step = iteration == MAX_TOOL_STEPS - 2
        final_hint = (
            "\n\n[SYSTEM: это последний доступный шаг. "
            "Сформулируй финальный ответ на основе уже полученных данных. "
            "НЕ вызывай инструменты.]"
        ) if is_last_step else None
        return self.gemini.continue_with_tool_results(
            turn_history, results, declarations, model=GEMINI_MODEL_SMART,
            extra_instruction=final_hint,
        )

    def _append_turn(self, turn_history, results, resp_content):
        if resp_content:
            turn_history.append(types.Content(parts=[
                types.Part.from_function_response(name=r["name"], response=r["result"])
                for r in results
            ]))
            turn_history.append(resp_content)

    def _log_repeated_failures(self, failed_tools):
        errors = "; ".join(f"{n}: {c}x" for n, c in failed_tools.items() if c >= 2)
        logger.warning("Breaking ReAct loop — repeated tool failures: %s", errors)
        self.log("loop_break", {"reason": "repeated failures", "details": errors})
