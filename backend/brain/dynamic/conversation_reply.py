from __future__ import annotations

import logging

from backend.brain.base_genai import BaseGenAI
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from backend.infrastructure.memory.retriever import KnowledgeRetriever

logger = logging.getLogger(__name__)


class ConversationReply(BaseGenAI):

    def __init__(self, gemini: GeminiGateway, retriever: KnowledgeRetriever,
                 tool_router: BaseGenAI | None = None,
                 query_tools: dict[str, BaseGenAI] | None = None):
        super().__init__(gemini)
        self._model = "gemini-3-flash-preview"
        self._retriever = retriever
        self._tool_router = tool_router
        self._query_tools = query_tools

    def _pick_template(self, input: str, context: dict) -> str:
        return "chat/conversation.md"

    def _build_context(self, input: str, context: dict) -> dict:
        verbose = context.get("verbose", False)
        environment = context.get("environment", "")
        user_context = context.get("user_context", "")
        conversation_history = context.get("conversation_history", "")
        allowed_domains: list[str] | None = context.get("allowed_domains")

        # Tool routing
        tool_calls = None
        if self._tool_router and self._query_tools:
            try:
                tool_calls = self._tool_router.run(input, {})
            except Exception:
                logger.warning("ToolRouter failed, falling back to RAG-only", exc_info=True)

        context_parts = []

        # RAG retrieval
        if allowed_domains is not None:
            core = self._retriever.get_multi_domain_context(allowed_domains)
            relevant = self._retriever.retrieve(input, domains=allowed_domains)
        else:
            core = self._retriever.get_core()
            relevant = self._retriever.retrieve(input)
        rag_context = core + "\n\n" + relevant if core else relevant
        context_parts.append(rag_context)

        # DB queries from tool routing
        if tool_calls and self._query_tools:
            tools_list = tool_calls.get("tools", [])
            for t in tools_list:
                name = t.get("name", "")
                if name == "rag":
                    continue
                query_tool = self._query_tools.get(name)
                if not query_tool:
                    continue
                try:
                    result = query_tool.run(t.get("query", input), {})
                    rows = result.get("rows", [])
                    if rows:
                        lines = []
                        for row in rows:
                            parts = [f"{k}: {v}" for k, v in row.items()]
                            lines.append(" | ".join(parts))
                        context_parts.append(f"## Данные из {name}\n" + "\n".join(lines))
                    elif result.get("error"):
                        context_parts.append(f"## Данные из {name}\n(запрос не удался: {result['error']})")
                except Exception:
                    logger.warning("QueryTool %s failed", name, exc_info=True)

        knowledge_context = "\n\n".join(context_parts)
        verbose_text = "Можешь дать развёрнутый ответ." if verbose else "Отвечай кратко и по делу."

        return {
            "VERBOSE": verbose_text,
            "ENVIRONMENT": environment or "(контекст не указан)",
            "USER_CONTEXT": user_context or "",
            "KNOWLEDGE": knowledge_context,
            "CONVERSATION": conversation_history,
            "MESSAGE": input,
        }

    def _parse_response(self, raw: dict) -> dict:
        return {"reply": raw.get("reply", str(raw))}
