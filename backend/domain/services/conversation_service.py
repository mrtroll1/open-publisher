"""Conversation business logic — context building and NL reply generation."""

from __future__ import annotations

import json
import logging

from backend.domain.services import compose_request
from backend.infrastructure.repositories.postgres import DbGateway
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from backend.domain.services.knowledge_retriever import KnowledgeRetriever
from backend.domain.services.query_tool import QueryTool
from backend.domain.services.tool_router import ToolRouter

logger = logging.getLogger(__name__)


def format_reply_chain(chain: list[dict]) -> str:
    parts = []
    for entry in chain:
        role = entry["role"]
        content = entry["content"]
        parts.append(f"{role}: {content}")
    return "\n".join(parts)


def build_conversation_context(
    chat_id: int,
    reply_message_id: int,
    reply_text: str,
    db: DbGateway,
    max_verbatim: int = 8,
) -> tuple[str, str | None]:
    """Look up conversation chain from DB; bootstrap from reply text if not found.

    Returns (history_str, parent_id).
    """
    conv_entry = db.get_conversation_by_message_id(chat_id, reply_message_id)

    if conv_entry:
        chain = db.get_reply_chain(conv_entry["id"], depth=20)
        if len(chain) > max_verbatim:
            skipped = len(chain) - max_verbatim
            chain = chain[-max_verbatim:]
            history = f"[{skipped} предыдущих сообщений опущено]\n" + format_reply_chain(chain)
        else:
            history = format_reply_chain(chain)
        return history, conv_entry["id"]

    history = f"assistant: {reply_text}"
    return history, None


def _format_query_results(results: dict) -> str:
    """Format QueryTool output for inclusion in context."""
    rows = results.get("rows", [])
    if not rows:
        error = results.get("error", "")
        if error:
            return f"(запрос не удался: {error})"
        return "(нет данных)"
    # Format as a compact table-like text
    lines = []
    for row in rows:
        parts = [f"{k}: {v}" for k, v in row.items()]
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def generate_nl_reply(
    message_text: str,
    conversation_history: str,
    retriever: KnowledgeRetriever,
    gemini: GeminiGateway | None = None,
    verbose: bool = False,
    environment: str = "",
    allowed_domains: list[str] | None = None,
    user_context: str = "",
    tool_router: ToolRouter | None = None,
    query_tools: dict[str, QueryTool] | None = None,
) -> str:
    """Build knowledge context (RAG + DB queries), call LLM, return reply text."""
    if gemini is None:
        gemini = GeminiGateway()

    # Decide which tools to use
    use_router = tool_router is not None and query_tools
    tool_calls = None
    if use_router:
        try:
            tool_calls = tool_router.route(message_text)
        except Exception:
            logger.warning("ToolRouter failed, falling back to RAG-only", exc_info=True)

    # Execute tools
    context_parts = []

    # RAG (always runs, either routed or default)
    if allowed_domains is not None:
        core = retriever.get_multi_domain_context(allowed_domains)
        relevant = retriever.retrieve(message_text, domains=allowed_domains)
    else:
        core = retriever.get_core()
        relevant = retriever.retrieve(message_text)
    rag_context = core + "\n\n" + relevant if core else relevant
    context_parts.append(rag_context)

    # DB queries (if router selected any)
    if tool_calls and query_tools:
        for call in tool_calls:
            if call.name == "rag":
                continue
            tool = query_tools.get(call.name)
            if not tool:
                continue
            try:
                result = tool.query(call.query)
                formatted = _format_query_results(result)
                context_parts.append(f"## Данные из {call.name}\n{formatted}")
            except Exception:
                logger.warning("QueryTool %s failed", call.name, exc_info=True)

    knowledge_context = "\n\n".join(context_parts)

    prompt, model, _ = compose_request.conversation_reply(
        message_text, conversation_history, knowledge_context,
        verbose=verbose, environment_context=environment,
        user_context=user_context,
    )

    result = gemini.call(prompt, model)
    answer = result.get("reply", str(result))

    return answer
