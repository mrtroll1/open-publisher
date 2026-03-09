from __future__ import annotations

from datetime import date

from backend.brain.tool import Tool, ToolContext
from backend.commands.budget import ComputeBudgetUseCase


def make_budget_tool(compute_budget) -> Tool:
    def _prev_month() -> str:
        today = date.today()
        if today.month == 1:
            return f"{today.year - 1}-12"
        return f"{today.year}-{today.month - 1:02d}"

    def fn(args: dict, ctx: ToolContext) -> dict:
        month = args.get("month") or args.get("input", "").strip() or _prev_month()
        use_case = ComputeBudgetUseCase(compute_budget)
        return use_case.execute({"month": month}, ctx.env, ctx.user)

    return Tool(
        name="budget",
        description="Генерация бюджетной таблицы",
        parameters={
            "type": "object",
            "properties": {
                "month": {"type": "string", "description": "Месяц в формате YYYY-MM"},
            },
        },
        fn=fn,
        permissions={},
        slash_command="budget",
        nl_routable=False,
        conversational=False,
    )
