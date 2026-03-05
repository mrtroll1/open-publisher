"""ToolRouter — decides which tools (RAG, republic_db, redefine_db) to use for a query."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from common.prompt_loader import load_template
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway

logger = logging.getLogger(__name__)


@dataclass
class ToolCall:
    name: str
    query: str


class ToolRouter:

    def __init__(self, gemini: GeminiGateway | None = None,
                 available_tools: list[str] | None = None):
        self._gemini = gemini or GeminiGateway()
        self._available_tools = available_tools or ["rag"]

    def route(self, question: str) -> list[ToolCall]:
        """Decide which tools to invoke for the given question."""
        tools_desc = "\n".join(f"- {t}" for t in self._available_tools)
        prompt = load_template("chat/require-tools.md", {
            "TOOLS": tools_desc,
            "QUESTION": question,
        })
        result = self._gemini.call(prompt)

        tools_raw = result.get("tools", [])
        calls = []
        for t in tools_raw:
            name = t.get("name", "")
            if name in self._available_tools:
                calls.append(ToolCall(name=name, query=t.get("query", question)))

        # Always include RAG as fallback
        if not calls:
            calls.append(ToolCall(name="rag", query=question))
        elif not any(c.name == "rag" for c in calls):
            calls.append(ToolCall(name="rag", query=question))

        return calls
