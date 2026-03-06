from __future__ import annotations

from backend.brain.tool import Tool, ToolContext


def make_invoice_tool(gen_invoice) -> Tool:
    def fn(args: dict, ctx: ToolContext) -> dict:
        from backend.commands.invoice import GenerateInvoiceUseCase
        use_case = GenerateInvoiceUseCase(gen_invoice)
        inp = args.get("input", "")
        if not inp:
            contractor = args.get("contractor", "")
            month = args.get("month", "")
            inp = f"{contractor} {month}".strip() if month else contractor
        parts = inp.strip().rsplit(maxsplit=1)
        if len(parts) == 2 and "-" in parts[1]:
            prepared = {"contractor": parts[0], "month": parts[1]}
        else:
            prepared = {"contractor": inp.strip(), "month": None}
        return use_case.execute(prepared, ctx.env, ctx.user)

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
        permissions={"*": {"admin"}},
        slash_command="generate",
        nl_routable=False,
        conversational=False,
    )
