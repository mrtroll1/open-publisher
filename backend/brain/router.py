from __future__ import annotations

from backend.brain.base_genai import BaseGenAI
from backend.brain.routes import Route
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway


class Router(BaseGenAI):
    def __init__(self, gemini: GeminiGateway):
        super().__init__(gemini)

    def route(self, input: str, routes: list[Route]) -> Route:
        context = {"routes": routes}
        result = self.run(input, context)
        route_name = result.get("command", "")
        matched = next((r for r in routes if r.name == route_name), None)
        if matched:
            return matched
        return next((r for r in routes if r.name == "conversation"), routes[0])

    def _pick_template(self, input: str, context: dict) -> str:
        return "chat/classify-command.md"

    def _build_context(self, input: str, context: dict) -> dict:
        routes = context["routes"]
        commands_desc = "\n".join(f"- **{r.name}** -- {r.description}" for r in routes)
        return {"COMMANDS": commands_desc, "TEXT": input, "CONTEXT": ""}

    def _parse_response(self, raw: dict) -> dict:
        return raw
