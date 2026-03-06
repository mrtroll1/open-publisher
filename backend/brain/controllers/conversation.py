"""Conversation controller — ReAct loop with Gemini function calling."""

from __future__ import annotations

import logging
from typing import Any

from backend.brain.authorizer import AuthContext
from backend.brain.tool import Tool, ToolContext
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from backend.infrastructure.memory.retriever import KnowledgeRetriever
from backend.infrastructure.repositories.postgres import DbGateway

logger = logging.getLogger(__name__)

MAX_TOOL_STEPS = 5


def _format_reply_chain(chain: list[dict]) -> str:
    parts = []
    for entry in chain:
        parts.append(f"{entry['type']}: {entry['text']}")
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
    parts = [
        "Ты — напарник Луки, издатель Republic. Ведёшь диалог в Telegram.",
        "Используй контекст и инструменты. Отвечай по-русски.",
        "Если не знаешь ответа — скажи.",
        "Отвечай кратко и по делу.",
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


def conversation_handler(
    gemini: GeminiGateway, db: DbGateway, retriever: KnowledgeRetriever,
) -> callable:
    """Create the conversation handler function used by Brain."""

    def handle(input: str, auth: AuthContext, **kwargs) -> dict:
        # Build conversation history
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

        # Build system prompt
        system_prompt = _build_system_prompt(env, user_context, knowledge, history)

        # Get conversational tools available to this user
        conv_tools = [t for t in auth.tools if t.conversational]
        declarations = _tool_declarations(conv_tools)
        tools_by_name = {t.name: t for t in conv_tools}

        if not declarations:
            # No tools available — plain call
            prompt = system_prompt + f"\n\n## Сообщение\n{input}\n\nВерни JSON: {{\"reply\": \"<ответ>\"}}"
            result = gemini.call(prompt, "gemini-3-flash-preview")
            reply = result.get("reply") or result.get("response") or result.get("answer") or "Не удалось сформировать ответ."
            return {"reply": reply, "parent_id": parent_id}

        # ReAct loop
        text, tool_calls, resp_content = gemini.call_with_tools(
            system_prompt, input, declarations, model="gemini-3-flash-preview",
        )
        # Build history for multi-turn
        from google.genai import types
        turn_history = [
            types.Content(role="user", parts=[types.Part.from_text(text=input)]),
        ]
        if resp_content:
            turn_history.append(resp_content)

        for step in range(MAX_TOOL_STEPS):
            if text:
                return {"reply": text, "parent_id": parent_id}

            if not tool_calls:
                return {"reply": "Не удалось сформировать ответ.", "parent_id": parent_id}

            # Execute tool calls
            results = []
            for tc in tool_calls:
                tool = tools_by_name.get(tc["name"])
                if not tool:
                    results.append({"name": tc["name"], "result": {"error": f"Unknown tool: {tc['name']}"}})
                    continue
                try:
                    result = tool.execute(tc["args"], auth.ctx)
                    results.append({"name": tc["name"], "result": result})
                except Exception as e:
                    logger.warning("Tool %s failed: %s", tc["name"], e, exc_info=True)
                    results.append({"name": tc["name"], "result": {"error": str(e)}})

            # Continue conversation with tool results
            text, tool_calls, resp_content = gemini.continue_with_tool_results(
                turn_history, results, declarations, model="gemini-3-flash-preview",
            )
            if resp_content:
                # Add tool result content + new response to history
                turn_history.append(types.Content(parts=[
                    types.Part.from_function_response(name=r["name"], response=r["result"])
                    for r in results
                ]))
                turn_history.append(resp_content)

        return {"reply": text or "Превышен лимит шагов.", "parent_id": parent_id}

    return handle
