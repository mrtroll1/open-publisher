from __future__ import annotations

import logging

from backend.brain.prompt_loader import load_template
from backend.brain.tool import Tool, ToolContext

logger = logging.getLogger(__name__)


def make_teach_tool(classify_teaching, memory, gemini) -> Tool:
    def _classify(content: str, args: dict) -> tuple[str, str]:
        domain = args.get("domain")
        tier = args.get("tier", "specific")
        if domain:
            return domain, tier
        result = classify_teaching.run(content, {})
        return result["domain"], result.get("tier", tier)

    def fn(args: dict, _ctx: ToolContext) -> dict:
        text = args.get("text") or args.get("input", "")
        extracted = _extract_knowledge(gemini, text, args.get("context", ""))
        title = extracted.get("title", "")
        content = extracted.get("content", text)
        domain, tier = _classify(content, args)
        entry_id = memory.teach(content, domain, tier, title=title)
        return {
            "confirmation": f"Запомнил: {title}" if title else "Запомнил!",
            "entry_id": entry_id, "domain": domain, "tier": tier, "title": title,
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
        permissions={"*": {"admin"}, "editorial_group": {"*"}},
        slash_command="teach",
        examples=["запомни, что я сейчас скажу ..."],
        nl_routable=True,
        conversational=True,
    )
