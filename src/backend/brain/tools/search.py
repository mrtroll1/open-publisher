from __future__ import annotations

from backend.brain.tool import Tool, ToolContext


def make_search_tool(retriever) -> Tool:
    def fn(args: dict, ctx: ToolContext) -> dict:
        query = args.get("query") or args.get("input", "")
        domain = args.get("domain")
        role = ctx.user.get("role", "user") if ctx.user else "user"
        user_id = ctx.user.get("id") if ctx.user else None
        env_name = ctx.env.get("name")
        text = retriever.retrieve(
            query, role=role, user_id=user_id, environment=env_name, domain=domain,
        )
        return {"results": text}

    return Tool(
        name="search",
        description="Поиск по базе знаний",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Поисковый запрос"},
                "domain": {"type": "string", "description": "Домен для поиска (опционально)"},
            },
            "required": ["query"],
        },
        fn=fn,
        permissions={"*": {"admin"}, "editorial_group": {"*"}, "ceo_group": {"*"}},
        slash_command="search",
        examples=["найди информацию про ...", "что мы знаем о ..."],
        nl_routable=True,
        conversational=True,
    )
