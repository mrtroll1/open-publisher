from __future__ import annotations

from backend.brain.tool import Tool, ToolContext
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway


def make_web_search_tool(gemini: GeminiGateway) -> Tool:
    def fn(args: dict, _ctx: ToolContext) -> dict:
        query = args.get("query", "")
        result = gemini.search_web(query)
        return {"results": result}

    return Tool(
        name="web_search",
        description="Поиск в интернете через Google. Используй для актуальной информации, трендов, курсов, каналов, новостей и всего, чего нет в базе знаний.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Поисковый запрос"},
            },
            "required": ["query"],
        },
        fn=fn,
        permissions={},
        nl_routable=False,
        conversational=True,
    )
