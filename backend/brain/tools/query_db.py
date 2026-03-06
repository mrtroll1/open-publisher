from __future__ import annotations

from backend.brain.tool import Tool, ToolContext


def make_query_db_tools(query_db_map: dict) -> list[Tool]:
    tools = []
    for db_name, query_db in query_db_map.items():
        def _make_fn(qdb):
            def fn(args: dict, ctx: ToolContext) -> dict:
                result = qdb.run(args["question"], {})
                rows = result.get("rows", [])
                if rows:
                    lines = []
                    for row in rows:
                        parts = [f"{k}: {v}" for k, v in row.items()]
                        lines.append(" | ".join(parts))
                    formatted = "\n".join(lines)
                else:
                    formatted = result.get("error") or "Нет результатов"
                return {"result": formatted, "sql": result.get("sql", "")}
            return fn

        tools.append(Tool(
            name=db_name,
            description=f"SQL-запрос к базе данных {db_name}",
            parameters={
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "Вопрос на естественном языке для формирования SQL-запроса"},
                },
                "required": ["question"],
            },
            fn=_make_fn(query_db),
            permissions={"*": {"admin"}},
            nl_routable=False,
            conversational=True,
        ))
    return tools
