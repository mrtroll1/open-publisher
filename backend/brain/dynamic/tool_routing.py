from __future__ import annotations

from backend.brain.base_genai import BaseGenAI
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway


class ToolRouting(BaseGenAI):

    def __init__(self, gemini: GeminiGateway, available_tools: list[str] | None = None):
        super().__init__(gemini)
        self._available_tools = available_tools or ["rag"]

    def _pick_template(self, input: str, context: dict) -> str:
        return "chat/require-tools.md"

    def _build_context(self, input: str, context: dict) -> dict:
        tools_desc = "\n".join(f"- {t}" for t in self._available_tools)
        return {
            "TOOLS": tools_desc,
            "QUESTION": input,
        }

    def run(self, input: str, context: dict, *, _depth: int = 0) -> dict:
        result = super().run(input, context, _depth=_depth)
        # Backfill empty queries with the original input (matches ToolRouter behavior)
        for call in result.get("tools", []):
            if not call.get("query"):
                call["query"] = input
        return result

    def _parse_response(self, raw: dict) -> dict:
        tools_raw = raw.get("tools", [])
        calls = []
        for t in tools_raw:
            name = t.get("name", "")
            if name in self._available_tools:
                calls.append({"name": name, "query": t.get("query", "")})

        # Always include RAG as fallback
        if not calls:
            calls.append({"name": "rag", "query": ""})
        elif not any(c["name"] == "rag" for c in calls):
            calls.append({"name": "rag", "query": ""})

        return {"tools": calls}
