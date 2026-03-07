"""Conversation controller — ReAct loop with Gemini function calling."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from backend.brain.authorizer import AuthContext
from backend.brain.tool import Tool
from backend.config import GEMINI_MODEL_SMART
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
            import json
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
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone(timedelta(hours=1)))
    parts = [
        f"Текущая дата и время: {now.strftime('%Y-%m-%d %H:%M')} (CET)",
        "Ты — Иван Добровольский, издатель Republic. Ведёшь диалог в Telegram.",
        "Используй контекст и инструменты. Отвечай по-русски.",
        "Если не знаешь ответа — скажи.",
        "Отвечай кратко и по делу.",
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
        progress = kwargs.get("progress")
        run_id = str(uuid.uuid4())
        step = 0

        def _log(type: str, content: dict):
            nonlocal step
            try:
                db.log_run_step(run_id, step, type, content)
            except Exception:
                logger.debug("Failed to write run log step %d", step)
            step += 1

        def _reply(text: str) -> dict:
            _log("llm_reply", {"reply": _truncate(text)})
            return {"reply": text, "parent_id": parent_id, "run_id": run_id}

        # Build conversation history
        if progress:
            progress.emit("context", "Загружаю контекст")
        history = ""
        parent_id = None
        chat_id = kwargs.get("chat_id")
        reply_to_message_id = kwargs.get("reply_to_message_id")
        reply_to_text = kwargs.get("reply_to_text", "")

        if chat_id and reply_to_message_id:
            history, parent_id = _build_conversation_context(
                chat_id, reply_to_message_id, reply_to_text, db,
            )

        # User context
        user_context = ""
        user = auth.ctx.user
        if user and user.get("id"):
            user_context = retriever.get_user_context(user["id"])

        # RAG context
        env = auth.ctx.env
        allowed_domains = env.get("allowed_domains")
        if allowed_domains is not None:
            core = retriever.get_multi_domain_context(allowed_domains)
            relevant = retriever.retrieve(input, domains=allowed_domains)
        else:
            core = retriever.get_core()
            relevant = retriever.retrieve(input)
        knowledge = (core + "\n\n" + relevant) if core else relevant

        system_prompt = _build_system_prompt(env, user_context, knowledge, history)

        conv_tools = [t for t in auth.tools if t.conversational]
        declarations = _tool_declarations(conv_tools)
        tools_by_name = {t.name: t for t in conv_tools}

        _log("input", {
            "user_input": input,
            "environment": env.get("name", ""),
            "tools": [t.name for t in conv_tools],
            "has_history": bool(history),
        })

        if not declarations:
            if progress:
                progress.emit("llm", "Генерирую ответ")
            prompt = system_prompt + f"\n\n## Сообщение\n{input}\n\nВерни JSON: {{\"reply\": \"<ответ>\"}}"
            result = gemini.call(prompt, GEMINI_MODEL_SMART)
            reply = result.get("reply") or result.get("response") or result.get("answer") or "Не удалось сформировать ответ."
            return _reply(reply)

        # ReAct loop
        if progress:
            progress.emit("llm", "Думаю...")
        text, tool_calls, resp_content = gemini.call_with_tools(
            system_prompt, input, declarations, model=GEMINI_MODEL_SMART,
        )
        from google.genai import types
        turn_history = [
            types.Content(role="user", parts=[types.Part.from_text(text=input)]),
        ]
        if resp_content:
            turn_history.append(resp_content)

        failed_tools: dict[str, int] = {}
        for iteration in range(MAX_TOOL_STEPS):
            if text:
                return _reply(text)
            if not tool_calls:
                return _reply("Не удалось сформировать ответ.")

            tool_names = ", ".join(tc["name"] for tc in tool_calls)
            if progress:
                progress.emit("tool", f"Вызываю {tool_names}")
            results = _execute_tool_calls(tool_calls, tools_by_name, auth.ctx, failed_tools, _log)

            if _has_repeated_failures(failed_tools):
                errors = "; ".join(f"{n}: {c}x" for n, c in failed_tools.items() if c >= 2)
                logger.warning("Breaking ReAct loop — repeated tool failures: %s", errors)
                _log("loop_break", {"reason": "repeated failures", "details": errors})
                break

            if progress:
                progress.emit("llm", f"Думаю... (шаг {iteration + 2})")
            is_last_step = iteration == MAX_TOOL_STEPS - 2
            final_hint = (
                "\n\n[SYSTEM: это последний доступный шаг. "
                "Сформулируй финальный ответ на основе уже полученных данных. "
                "НЕ вызывай инструменты.]"
            ) if is_last_step else None
            text, tool_calls, resp_content = gemini.continue_with_tool_results(
                turn_history, results, declarations, model=GEMINI_MODEL_SMART,
                extra_instruction=final_hint,
            )
            if resp_content:
                turn_history.append(types.Content(parts=[
                    types.Part.from_function_response(name=r["name"], response=r["result"])
                    for r in results
                ]))
                turn_history.append(resp_content)

        return _reply(text or "Превышен лимит шагов.")

    return handle
