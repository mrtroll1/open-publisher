from __future__ import annotations

from backend.brain.tool import Tool, ToolContext
from backend.commands.ingest_articles import IngestUseCase


def make_ingest_tool(summarizer, memory) -> Tool:
    def fn(args: dict, ctx: ToolContext) -> dict:
        use_case = IngestUseCase(summarizer, memory)
        return use_case.execute(args.get("input", ""), ctx.env, ctx.user)

    return Tool(
        name="ingest",
        description="Загрузка и обработка статей",
        parameters={
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "URL или текст для загрузки"},
            },
            "required": ["input"],
        },
        fn=fn,
        permissions={"*": {"admin"}},
        slash_command="ingest_articles",
        nl_routable=False,
        conversational=False,
    )
