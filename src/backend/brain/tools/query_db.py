from __future__ import annotations

from backend.brain.tool import Tool, ToolContext

_DB_DESCRIPTIONS = {
    "republic_db": "SQL-запрос к основной базе Republic (users, posts, user_comments, authors, magazines)",
    "redefine_db": "SQL-запрос к базе Redefine (users, subscriptions, payment_transaction, read_stats - статистика по ридам, но самих статей в этой бд нет)",
    "agent_db": "SQL-запрос к внутренней базе агента (messages, units_of_knowledge, users, environments, run_logs, tool_permissions)",
}


def _format_query_result(result: dict) -> str:
    rows = result.get("rows", [])
    if not rows:
        return result.get("error") or "Нет результатов"
    return "\n".join(" | ".join(f"{k}: {v}" for k, v in row.items()) for row in rows)


def _make_query_fn(qdb):
    def fn(args: dict, _ctx: ToolContext) -> dict:
        result = qdb.run(args["question"], {})
        return {"result": _format_query_result(result), "sql": result.get("sql", "")}
    return fn


def make_query_db_tools(query_db_map: dict) -> list[Tool]:
    return [
        Tool(
            name=db_name,
            description=_DB_DESCRIPTIONS.get(db_name, f"SQL-запрос к базе данных {db_name}"),
            parameters={
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "Вопрос на естественном языке для формирования SQL-запроса"},
                },
                "required": ["question"],
            },
            fn=_make_query_fn(query_db),
            permissions={},
            nl_routable=False,
            conversational=True,
        )
        for db_name, query_db in query_db_map.items()
    ]
