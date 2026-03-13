from __future__ import annotations

from backend.brain.tool import Tool, ToolContext
from backend.commands.invoice import GenerateInvoiceUseCase


def _parse_invoice_input(args: dict) -> dict:
    contractor = args.get("contractor", "")
    month = args.get("month", "")
    inp = f"{contractor} {month}".strip() if month else contractor
    parts = inp.strip().rsplit(maxsplit=1)
    if len(parts) == 2 and "-" in parts[1]:
        return {"contractor": parts[0], "month": parts[1]}
    return {"contractor": inp.strip(), "month": None}


def make_invoice_tool(gen_invoice) -> Tool:
    def fn(args: dict, ctx: ToolContext) -> dict:
        prepared = _parse_invoice_input(args)
        return GenerateInvoiceUseCase(gen_invoice).execute(prepared, ctx.env, ctx.user)

    return Tool(
        name="invoice",
        description="Генерация счёта для автора",
        parameters={
            "type": "object",
            "properties": {
                "contractor": {"type": "string", "description": "Имя автора"},
                "month": {"type": "string", "description": "Месяц в формате YYYY-MM"},
            },
            "required": ["contractor"],
        },
        fn=fn,
        permissions={},
        slash_command="generate",
        nl_routable=False,
        conversational=False,
        nl_param="contractor",
    )
