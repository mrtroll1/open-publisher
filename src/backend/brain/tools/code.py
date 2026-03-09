from __future__ import annotations

from backend.brain.tool import Tool, ToolContext
from backend.commands.run_code import run_claude_code


def make_code_tool() -> Tool:
    def fn(args: dict, _ctx: ToolContext) -> dict:
        prompt = args.get("prompt") or args.get("input", "")
        result = run_claude_code(
            prompt,
            verbose=args.get("verbose", False),
            expert=args.get("expert", False),
            mode="explore",
            resume_session_id=args.get("resume_session"),
        )
        return {"text": result.text, "session_id": result.session_id}

    return Tool(
        name="code",
        description="Работа с кодом, архитектура, баги",
        parameters={
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Задача для Claude Code"},
            },
            "required": ["prompt"],
        },
        fn=fn,
        permissions={},
        slash_command="code",
        examples=["как нам скрыть лайки?", "можем ли мы изменить дизайн рассылки?"],
        nl_routable=True,
        conversational=False,
    )
