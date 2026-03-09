from __future__ import annotations

from backend.brain.tool import Tool, ToolContext
from backend.commands.check_health import CheckHealthUseCase, format_healthcheck_results


def make_health_tool() -> Tool:
    def fn(_args: dict, ctx: ToolContext) -> dict:
        results = CheckHealthUseCase().execute(None, ctx.env, ctx.user)
        return {"text": format_healthcheck_results(results)}

    return Tool(
        name="health",
        description="Проверка доступности сервисов",
        parameters={"type": "object", "properties": {}},
        fn=fn,
        permissions={},
        slash_command="health",
        examples=["лежит сайт", "всё ли работает?"],
        nl_routable=True,
        conversational=False,
    )
