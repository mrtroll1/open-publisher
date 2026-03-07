"""Brain tools for Yandex Metrica and Cloudflare analytics."""

from __future__ import annotations

from backend.brain.tool import Tool, ToolContext
from backend.infrastructure.gateways.cloudflare_gateway import CloudflareGateway
from backend.infrastructure.gateways.yandex_metrica_gateway import YandexMetricaGateway

_METRICA_METHODS = {
    "popular_pages": "Топ страниц по просмотрам",
    "traffic_summary": "Общая сводка трафика (визиты, просмотры, отказы)",
    "traffic_sources": "Источники трафика",
    "daily_traffic": "Трафик по дням",
}

_CLOUDFLARE_METHODS = {
    "traffic_summary": "Общая сводка (запросы, уникальные посетители, кеш, угрозы)",
    "daily_traffic": "Трафик по дням",
    "status_codes": "Статус-коды HTTP",
}


def _format_rows(rows: list[dict]) -> str:
    if not rows:
        return "Нет данных"
    lines = []
    for row in rows:
        parts = [f"{k}: {v}" for k, v in row.items()]
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def _format_summary(data: dict | None) -> str:
    if not data:
        return "Нет данных"
    return " | ".join(f"{k}: {v}" for k, v in data.items())


def make_yandex_metrica_tool(gw: YandexMetricaGateway) -> Tool:
    def fn(args: dict, ctx: ToolContext) -> dict:
        method = args["method"]
        date_from = args["date_from"]
        date_to = args["date_to"]
        limit = args.get("limit", 20)

        if method == "popular_pages":
            result = _format_rows(gw.get_popular_pages(date_from, date_to, limit))
        elif method == "traffic_summary":
            result = _format_summary(gw.get_traffic_summary(date_from, date_to))
        elif method == "traffic_sources":
            result = _format_rows(gw.get_traffic_sources(date_from, date_to, limit))
        elif method == "daily_traffic":
            result = _format_rows(gw.get_daily_traffic(date_from, date_to))
        else:
            result = f"Неизвестный метод: {method}"

        return {"result": result}

    methods_desc = ", ".join(f"{k} ({v})" for k, v in _METRICA_METHODS.items())

    return Tool(
        name="yandex_metrica",
        description=f"Аналитика сайта republicmag.io из Яндекс Метрики. Методы: {methods_desc}",
        parameters={
            "type": "object",
            "properties": {
                "method": {
                    "type": "string",
                    "enum": list(_METRICA_METHODS.keys()),
                    "description": "Метод аналитики",
                },
                "date_from": {"type": "string", "description": "Дата начала (YYYY-MM-DD)"},
                "date_to": {"type": "string", "description": "Дата конца (YYYY-MM-DD)"},
                "limit": {"type": "integer", "description": "Количество результатов (по умолчанию 20)"},
            },
            "required": ["method", "date_from", "date_to"],
        },
        fn=fn,
        permissions={"*": {"admin"}, "editorial_group": {"*"}},
        nl_routable=False,
        conversational=True,
    )


def make_cloudflare_tool(gw: CloudflareGateway) -> Tool:
    def fn(args: dict, ctx: ToolContext) -> dict:
        method = args["method"]
        date_from = args["date_from"]
        date_to = args["date_to"]

        if method == "traffic_summary":
            result = _format_summary(gw.get_traffic_summary(date_from, date_to))
        elif method == "daily_traffic":
            result = _format_rows(gw.get_daily_traffic(date_from, date_to))
        elif method == "status_codes":
            result = _format_rows(gw.get_status_codes(date_from, date_to))
        else:
            result = f"Неизвестный метод: {method}"

        return {"result": result}

    methods_desc = ", ".join(f"{k} ({v})" for k, v in _CLOUDFLARE_METHODS.items())

    return Tool(
        name="cloudflare",
        description=f"Аналитика Cloudflare для republicmag.io. Методы: {methods_desc}",
        parameters={
            "type": "object",
            "properties": {
                "method": {
                    "type": "string",
                    "enum": list(_CLOUDFLARE_METHODS.keys()),
                    "description": "Метод аналитики",
                },
                "date_from": {"type": "string", "description": "Дата начала (YYYY-MM-DD)"},
                "date_to": {"type": "string", "description": "Дата конца (YYYY-MM-DD)"},
            },
            "required": ["method", "date_from", "date_to"],
        },
        fn=fn,
        permissions={"*": {"admin"}, "editorial_group": {"*"}},
        nl_routable=False,
        conversational=True,
    )
