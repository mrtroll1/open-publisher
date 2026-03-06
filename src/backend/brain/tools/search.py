from __future__ import annotations

from backend.brain.tool import Tool, ToolContext


def make_search_tool(retriever) -> Tool:
    def fn(args: dict, ctx: ToolContext) -> dict:
        query = args.get("query") or args.get("input", "")
        domain = args.get("domain")
        if domain:
            text = retriever.retrieve(query, domain=domain)
        else:
            allowed = ctx.env.get("allowed_domains")
            text = retriever.retrieve(query, domains=allowed)
        return {"results": text}

    return Tool(
        name="search",
        description="Поиск по базе знаний",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Поисковый запрос"},
                "domain": {"type": "string", "description": "Домен для поиска"},
            },
            "required": ["query"],
        },
        fn=fn,
        permissions={"*": {"admin"}, "editorial_group": {"admin", "editor"}},
        slash_command="search",
        examples=["найди информацию про ...", "что мы знаем о ..."],
        nl_routable=True,
        conversational=True,
    )
