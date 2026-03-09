from __future__ import annotations

import logging

from backend.brain.prompt_loader import load_template
from backend.brain.tool import Tool, ToolContext

logger = logging.getLogger(__name__)


def make_teach_tool(classify_teaching, memory, gemini) -> Tool:
    def _classify(content: str, args: dict) -> dict:
        domain = args.get("domain")
        tier = args.get("tier", "specific")
        if domain:
            return {"domain": domain, "tier": tier, "visibility": args.get("visibility", "public")}
        return classify_teaching.run(content, {})

    def fn(args: dict, _ctx: ToolContext) -> dict:
        text = args.get("text") or args.get("input", "")
        extracted = _extract_knowledge(gemini, text, args.get("context", ""))
        content = extracted.get("content", text)
        classified = _classify(content, args)
        domain = classified["domain"]
        tier = classified.get("tier", "specific")
        visibility = classified.get("visibility", "public")
        entry_id = memory.teach(content, domain, tier, visibility=visibility)
        return {
            "confirmation": "Запомнил!",
            "entry_id": entry_id, "domain": domain, "tier": tier,
            "visibility": visibility,
        }

    def _extract_knowledge(gemini_gw, message: str, context: str) -> dict:
        prompt = load_template("knowledge/extract-teaching.md", {
            "CONTEXT": context or "(нет контекста)",
            "MESSAGE": message,
        })
        try:
            return gemini_gw.call(prompt)
        except Exception:
            logger.warning("Knowledge extraction failed, storing raw text")
            return {"title": "", "content": message}

    return Tool(
        name="teach",
        description="Запомнить новое знание. Передай text (что запомнить) и context (предыдущие сообщения из переписки для контекста).",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Сообщение пользователя с просьбой запомнить"},
                "context": {"type": "string", "description": "Предыдущие сообщения из переписки (для контекста)"},
                "domain": {"type": "string", "description": "Домен знаний (определяется автоматически если не указан)"},
                "tier": {"type": "string", "description": "Уровень: core, meta, specific"},
            },
            "required": ["text"],
        },
        fn=fn,
        permissions={},
        slash_command="teach",
        examples=["запомни, что я сейчас скажу ..."],
        nl_routable=True,
        conversational=True,
    )
