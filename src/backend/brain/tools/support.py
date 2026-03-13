from __future__ import annotations

from backend.brain.tool import Tool, ToolContext


def make_support_tool(tech_support) -> Tool:
    def fn(args: dict, ctx: ToolContext) -> dict:
        question = args.get("question", "")
        return tech_support.run(question, {"env": ctx.env, "user": ctx.user})

    return Tool(
        name="support",
        description="Техподдержка: вопросы о продукте, сайте, подписке",
        parameters={
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Вопрос пользователя"},
            },
            "required": ["question"],
        },
        fn=fn,
        permissions={},
        slash_command="support",
        examples=["как отменить подписку?", "не работает оплата"],
        nl_routable=True,
        conversational=False,
        nl_param="question",
    )
