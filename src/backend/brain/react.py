"""ReAct loop — Gemini function-calling with tool execution."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from google.genai import types

from backend.brain.authorizer import AuthContext
from backend.brain.context import (
    build_conversation_context,
    build_system_prompt,
    tool_declarations,
)
from backend.brain.tool import Tool
from backend.config import GEMINI_MODEL_SMART
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from backend.infrastructure.memory.retriever import KnowledgeRetriever
from backend.infrastructure.repositories.postgres import DbGateway

logger = logging.getLogger(__name__)

MAX_TOOL_STEPS = 5


def _truncate(obj, max_len=500) -> Any:
    """Truncate long strings in dicts for logging."""
    if isinstance(obj, str):
        return obj[:max_len] + "…" if len(obj) > max_len else obj
    if isinstance(obj, dict):
        return {k: _truncate(v, max_len) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_truncate(v, max_len) for v in obj]
    return obj


def _run_single_tool(tc, tool, auth_ctx, failed_tools, _log) -> dict:
    try:
        result = tool.execute(tc["args"], auth_ctx)
        if isinstance(result, dict) and result.get("error"):
            failed_tools[tc["name"]] = failed_tools.get(tc["name"], 0) + 1
        _log("tool_result", {"tool": tc["name"], "result": _truncate(result)})
        return {"name": tc["name"], "result": result}
    except Exception as e:
        logger.warning("Tool %s failed: %s", tc["name"], e, exc_info=True)
        failed_tools[tc["name"]] = failed_tools.get(tc["name"], 0) + 1
        _log("tool_error", {"tool": tc["name"], "error": str(e)})
        return {"name": tc["name"], "result": {"error": str(e)}}


def _execute_tool_calls(tool_calls, tools_by_name, auth_ctx, failed_tools, _log):
    results = []
    for tc in tool_calls:
        _log("tool_call", {"tool": tc["name"], "args": _truncate(tc["args"])})
        tool = tools_by_name.get(tc["name"])
        if not tool:
            results.append({"name": tc["name"], "result": {"error": f"Unknown tool: {tc['name']}"}})
            _log("tool_error", {"tool": tc["name"], "error": "unknown tool"})
            continue
        results.append(_run_single_tool(tc, tool, auth_ctx, failed_tools, _log))
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
        ctx.load_goals()
        system_prompt = build_system_prompt(
            auth.ctx.env, ctx.user_context, ctx.knowledge,
            ctx.history, goals_summary=ctx.goals_summary,
        )
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
        self.goals_summary = ""

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
            self.history, self.parent_id = build_conversation_context(
                self.chat_id, self.reply_to_message_id, self.reply_to_text, self.db,
            )

    def load_knowledge(self):
        user = self.auth.ctx.user
        if user and user.get("id"):
            self.user_context = self.retriever.get_user_context(user["id"])
        role = self.auth.role
        user_id = user.get("id") if user else None
        env_name = self.auth.env_name
        context = self.retriever.get_context(role=role, user_id=user_id, environment=env_name)
        relevant = self.retriever.retrieve(
            self.input, role=role, user_id=user_id, environment=env_name,
        )
        self.knowledge = (context + "\n\n" + relevant) if context else relevant

    def load_goals(self):
        if self.auth.role == "admin":
            self.goals_summary = self.db.get_active_goals_summary()

    def single_llm_call(self, system_prompt: str) -> dict:
        self._emit("llm", "Генерирую ответ")
        prompt = system_prompt + f"\n\n## Сообщение\n{self.input}\n\nВерни JSON: {{\"reply\": \"<ответ>\"}}"
        result = self.gemini.call(prompt, GEMINI_MODEL_SMART)
        reply = result.get("reply") or result.get("raw_parsed") or "Не удалось сформировать ответ."
        return self._reply(reply)

    def react_loop(self, system_prompt: str, conv_tools: list[Tool]) -> dict:
        declarations = tool_declarations(conv_tools)
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
