from __future__ import annotations

from backend.brain.base_genai import BaseGenAI
from backend.brain.tool import Tool
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway


class Router(BaseGenAI):
    def __init__(self, gemini: GeminiGateway):
        super().__init__(gemini)

    def route(self, input: str, tools: list[Tool], *, reply_context: str = "") -> Tool | None:
        """Classify NL input to a tool, or None for conversation mode."""
        routable = [t for t in tools if t.nl_routable]
        if not routable:
            return None
        context = {"tools": routable, "reply_context": reply_context}
        result = self.run(input, context)
        tool_name = result.get("command", "")
        if tool_name == "conversation":
            return None
        return next((t for t in routable if t.name == tool_name), None)

    def _pick_template(self, _input: str, _context: dict) -> str:
        return "chat/classify-command.md"

    def _build_context(self, input: str, context: dict) -> dict:
        tools = context["tools"]
        commands_desc = "\n".join(f"- **{t.name}** -- {t.description}" for t in tools)
        reply = context.get("reply_context", "")
        ctx = f"Это ответ на сообщение: «{reply[:200]}»" if reply else ""
        return {"COMMANDS": commands_desc, "TEXT": input, "CONTEXT": ctx}

    def _parse_response(self, raw: dict) -> dict:
        return raw
