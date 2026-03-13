from __future__ import annotations

import logging

from backend.brain.prompt_loader import load_template
from backend.brain.tool import Tool, ToolContext
from backend.infrastructure.repositories.postgres import DbGateway

logger = logging.getLogger(__name__)


def make_user_tool(db: DbGateway, gemini) -> Tool:  # noqa: C901
    def _extract(text: str) -> dict:
        prompt = load_template("users/extract-user.md", {"TEXT": text})
        try:
            return gemini.call(prompt)
        except Exception:
            logger.warning("User extraction failed")
            return {}

    def _resolve_fields(args: dict) -> dict:
        text = args.get("text", "")
        telegram_id = args.get("telegram_id")
        name = args.get("name", "")
        role = args.get("role", "")
        email = args.get("email")
        if text and (not telegram_id or not name):
            extracted = _extract(text)
            telegram_id = telegram_id or extracted.get("telegram_id")
            name = name or extracted.get("name", "")
            role = role or extracted.get("role", "user")
            email = email or extracted.get("email")
        return {"telegram_id": telegram_id, "name": name,
                "role": role or "user", "email": email}

    def _upsert(fields: dict) -> dict:
        telegram_id, name = fields["telegram_id"], fields["name"]
        role, email = fields["role"], fields["email"]
        user = (db.get_user_by_telegram_id(telegram_id) if telegram_id
                else db.get_user_by_email(email))
        if user:
            updates = {}
            if name:
                updates["name"] = name
            if role and role != user.get("role"):
                updates["role"] = role
            if email and not user.get("email"):
                updates["email"] = email
            if telegram_id and not user.get("telegram_id"):
                updates["telegram_id"] = telegram_id
            if updates:
                db.update_user(user["id"], **updates)
                user.update(updates)
            return {"user": user, "action": "updated" if updates else "found"}
        user_id = db.save_user(name=name, role=role, telegram_id=telegram_id, email=email)
        return {"user": db.get_user(user_id), "action": "created"}

    def fn(args: dict, _ctx: ToolContext) -> dict:
        logger.info("user tool args: %s", args)
        fields = _resolve_fields(args)
        logger.info("user tool resolved fields: %s", fields)
        if not fields["telegram_id"] and not fields["email"]:
            return {"error": "Не удалось определить telegram_id или email пользователя."}
        return _upsert(fields)

    return Tool(
        name="user",
        description="Добавить или обновить пользователя. Передай text с описанием на естественном языке, или структурированные поля.",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Описание пользователя на естественном языке"},
                "telegram_id": {"type": "integer", "description": "Telegram ID пользователя"},
                "name": {"type": "string", "description": "Имя пользователя"},
                "role": {"type": "string", "description": "Роль: user, editor, admin"},
                "email": {"type": "string", "description": "Email (опционально)"},
            },
        },
        fn=fn,
        permissions={},
        examples=["добавь пользователя ...", "это наш редактор ...", "Маша Иванова, telegram 123, editor"],
        nl_routable=True,
        conversational=True,
    )
