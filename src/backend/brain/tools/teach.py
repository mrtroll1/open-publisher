from __future__ import annotations

from backend.brain.tool import Tool, ToolContext


def make_teach_tool(classify_teaching, memory) -> Tool:
    def fn(args: dict, ctx: ToolContext) -> dict:
        text = args.get("text") or args.get("input", "")
        domain = args.get("domain")
        tier = args.get("tier", "specific")
        if not domain:
            result = classify_teaching.run(text, {})
            domain = result["domain"]
            tier = result.get("tier", tier)
        entry_id = memory.teach(text, domain, tier)
        return {"entry_id": entry_id, "domain": domain, "tier": tier}

    return Tool(
        name="teach",
        description="Запомнить новое знание",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Текст для запоминания"},
                "domain": {"type": "string", "description": "Домен знаний (определяется автоматически если не указан)"},
                "tier": {"type": "string", "description": "Уровень: core, meta, specific"},
            },
            "required": ["text"],
        },
        fn=fn,
        permissions={"*": {"admin"}, "editorial_group": {"admin", "editor"}},
        slash_command="teach",
        examples=["запомни, что я сейчас скажу ..."],
        nl_routable=True,
        conversational=True,
    )
