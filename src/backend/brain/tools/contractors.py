"""Contractors tool — NL contractor operations for editors/admins."""

from __future__ import annotations

import logging

from backend.brain.tool import Tool, ToolContext
from backend.commands.contractor.create import ContractorFactory
from backend.infrastructure.repositories.sheets.contractor_repo import (
    find_contractor,
    fuzzy_find,
    load_all_contractors,
)
from backend.infrastructure.repositories.sheets.rules_repo import (
    add_redirect_rule,
    get_article_rate_rule,
    upsert_article_rate_rule,
)

logger = logging.getLogger(__name__)


def _lookup(args: dict) -> dict:
    query = args.get("name", "")
    if not query:
        return {"error": "Нужно указать name"}
    contractors = load_all_contractors()
    matches = fuzzy_find(query, contractors, threshold=0.5)
    if not matches:
        return {"result": "Контрагент не найден", "suggestions": []}
    return {"contractors": [
        {"id": c.id, "name": c.display_name,
         "type": "stub" if c.is_stub else c.type.value,
         "score": round(score, 2)}
        for c, score in matches[:5]
    ]}


def _create_stub(args: dict) -> dict:
    name = args.get("name", "")
    if not name:
        return {"error": "Нужно указать name"}
    contractors = load_all_contractors()
    existing = fuzzy_find(name, contractors, threshold=0.9)
    if existing:
        return {"error": f"«{existing[0][0].display_name}» уже существует"}
    stub, code = ContractorFactory().create_stub(name, contractors)
    return {"created": {"id": stub.id, "name": stub.display_name, "secret_code": code},
            "confirmation": f"Заглушка создана: {stub.display_name} ({stub.id})"}


def _add_redirect(args: dict) -> dict:
    source_name = args.get("source_name", "")
    target_name = args.get("target_name", "")
    if not source_name or not target_name:
        return {"error": "Нужны source_name и target_name"}
    contractors = load_all_contractors()
    target = find_contractor(target_name, contractors)
    if not target:
        return {"error": f"Контрагент «{target_name}» не найден"}
    add_redirect_rule(source_name, target.id)
    return {"confirmation": f"Редирект: {source_name} → {target.display_name} ({target.id})"}


def _set_rate(args: dict) -> dict:
    name = args.get("name", "")
    eur = args.get("eur", 0)
    rub = args.get("rub", 0)
    if not name:
        return {"error": "Нужно указать name"}
    if not eur and not rub:
        return {"error": "Нужно указать eur или rub"}
    contractors = load_all_contractors()
    contractor = find_contractor(name, contractors)
    if not contractor:
        return {"error": f"Контрагент «{name}» не найден"}
    upsert_article_rate_rule(contractor.id, eur=int(eur), rub=int(rub))
    return {"confirmation": f"Ставка для {contractor.display_name}: EUR {eur}, RUB {rub}"}


def _get_rate(args: dict) -> dict:
    name = args.get("name", "")
    if not name:
        return {"error": "Нужно указать name"}
    contractors = load_all_contractors()
    contractor = find_contractor(name, contractors)
    if not contractor:
        return {"error": f"Контрагент «{name}» не найден"}
    rule = get_article_rate_rule(contractor.id)
    if not rule:
        return {"result": f"Для {contractor.display_name} не задана поартикульная ставка"}
    return {"contractor": contractor.display_name, "eur": rule.eur, "rub": rule.rub}


_ACTIONS = {
    "lookup": _lookup,
    "create_stub": _create_stub,
    "add_redirect": _add_redirect,
    "set_rate": _set_rate,
    "get_rate": _get_rate,
}


def make_contractors_tool() -> Tool:
    def fn(args: dict, _ctx: ToolContext) -> dict:
        action = args.get("action", "lookup")
        handler = _ACTIONS.get(action)
        if not handler:
            return {"error": f"Unknown action: {action}"}
        return handler(args)

    return Tool(
        name="contractors",
        description="Управление контрагентами: поиск, создание заглушки, редиректы оплаты, ставки за статью",
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["lookup", "create_stub", "add_redirect", "set_rate", "get_rate"],
                    "description": "lookup=найти, create_stub=заглушка, add_redirect=редирект, set_rate=задать ставку, get_rate=узнать ставку",
                },
                "name": {"type": "string", "description": "Имя контрагента"},
                "source_name": {"type": "string", "description": "Имя-источник для редиректа"},
                "target_name": {"type": "string", "description": "Имя получателя редиректа"},
                "eur": {"type": "integer", "description": "Ставка EUR за статью"},
                "rub": {"type": "integer", "description": "Ставка RUB за статью"},
            },
            "required": ["action"],
        },
        fn=fn,
        permissions={},
        slash_command=None,
        examples=[
            "найди контрагента Иванов",
            "создай заглушку для нового автора",
            "я получаю ещё за Петрова",
            "автор X получает 150 евро за статью",
            "какая ставка у Иванова",
        ],
        nl_routable=True,
        conversational=True,
    )
