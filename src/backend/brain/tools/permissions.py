from __future__ import annotations

from backend.brain.tool import TOOLS, Tool, ToolContext
from backend.infrastructure.repositories.postgres import DbGateway


def _list(db, args):
    tool_filter = args.get("tool_name")
    perms = db.list_permissions()
    if tool_filter:
        perms = [p for p in perms if p["tool_name"] == tool_filter]
    return {"permissions": perms}


def _grant(db, args):
    tool_name = args.get("tool_name")
    environment = args.get("environment", "*")
    roles = args.get("roles", ["*"])
    if not tool_name:
        return {"error": "Укажи имя инструмента (tool_name)."}
    if tool_name not in TOOLS:
        return {"error": f"Инструмент '{tool_name}' не найден. Доступные: {', '.join(sorted(TOOLS.keys()))}"}
    db.grant(tool_name, environment, roles)
    return {"result": f"Доступ выдан: {tool_name} → {environment} [{', '.join(roles)}]"}


def _revoke(db, args):
    tool_name = args.get("tool_name")
    environment = args.get("environment")
    if not tool_name or not environment:
        return {"error": "Укажи tool_name и environment."}
    ok = db.revoke(tool_name, environment)
    if not ok:
        return {"error": f"Правило {tool_name} → {environment} не найдено."}
    return {"result": f"Удалено: {tool_name} → {environment}"}


_ACTIONS = {"list": _list, "grant": _grant, "revoke": _revoke}


def make_permissions_tool(db: DbGateway) -> Tool:
    def fn(args: dict, _ctx: ToolContext) -> dict:
        action = args.get("action", "list")
        handler = _ACTIONS.get(action)
        if not handler:
            return {"error": f"Неизвестное действие: {action}. Доступные: list, grant, revoke."}
        return handler(db, args)

    return Tool(
        name="permissions",
        description="Управление правами доступа к инструментам. Показать, выдать или отозвать доступ к инструменту для окружения/роли.",
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "grant", "revoke"],
                    "description": "Действие: list (показать), grant (выдать доступ), revoke (отозвать)",
                },
                "tool_name": {
                    "type": "string",
                    "description": "Имя инструмента (budget, search, code, ...)",
                },
                "environment": {
                    "type": "string",
                    "description": "Имя окружения (* = везде по умолчанию)",
                },
                "roles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Роли: ['*'] = все, ['admin'], ['admin', 'editor'], ...",
                },
            },
        },
        fn=fn,
        permissions={},
        examples=[
            "какие разрешения у инструментов?",
            "какие права для budget?",
            "дай доступ к budget в editorial_group",
            "убери доступ к code в contractor_dm",
        ],
        nl_routable=True,
        conversational=True,
    )
