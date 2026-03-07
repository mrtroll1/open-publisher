"""Brain tools for Yandex Metrica and Cloudflare analytics."""

from __future__ import annotations

from backend.brain.tool import Tool, ToolContext
from backend.infrastructure.gateways.cloudflare_gateway import CloudflareGateway
from backend.infrastructure.gateways.yandex_metrica_gateway import YandexMetricaGateway

# Yandex Metrica — ПОВЕДЕНИЕ пользователей (клиентская JS-аналитика).
# Считает только реальных пользователей с загруженным JS-счётчиком.
# Используй для: качество аудитории, вовлечённость, источники трафика, отказы.
_METRICA_METHODS = {
    "traffic_summary": "Сводка: визиты, пользователи, показатель отказов, средняя длительность сессии",
    "traffic_sources": "Откуда приходят пользователи (поиск, соцсети, прямые, рефералы)",
    "popular_pages": "Топ страниц по просмотрам реальных пользователей",
    "daily_traffic": "Визиты и просмотры по дням",
}

# Cloudflare — ИНФРАСТРУКТУРА и нагрузка (серверная аналитика).
# Считает ВСЕ HTTP-запросы включая ботов, API, статику.
# Используй для: нагрузка на сервер, география, безопасность, кеширование, ошибки.
_CLOUDFLARE_METHODS = {
    "traffic_summary": "Сводка: все запросы, уникальные IP, bandwidth, кеш-ratio, заблокированные угрозы",
    "daily_traffic": "Запросы и bandwidth по дням",
    "top_paths": "Топ URL-путей по количеству HTTP-запросов (включая ботов)",
    "top_countries": "Топ стран по запросам",
    "status_codes": "Распределение HTTP статус-кодов (200, 301, 404, 500...)",
    "threat_summary": "Угрозы: типы атак, страны-источники",
    "content_types": "Разбивка по типам контента (HTML, JS, CSS, изображения...)",
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
    def fn(args: dict, _ctx: ToolContext) -> dict:
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

    methods_desc = "\n".join(f"- {k}: {v}" for k, v in _METRICA_METHODS.items())

    return Tool(
        name="yandex_metrica",
        description=(
            "Яндекс Метрика — ПОВЕДЕНИЕ реальных пользователей republicmag.io. "
            "Только люди (без ботов). Используй для вопросов про аудиторию, вовлечённость, "
            "источники трафика, показатель отказов.\n" + methods_desc
        ),
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
    def fn(args: dict, _ctx: ToolContext) -> dict:
        method = args["method"]
        date_from = args["date_from"]
        date_to = args["date_to"]

        limit = args.get("limit", 20)

        if method == "traffic_summary":
            result = _format_summary(gw.get_traffic_summary(date_from, date_to))
        elif method == "daily_traffic":
            result = _format_rows(gw.get_daily_traffic(date_from, date_to))
        elif method == "status_codes":
            result = _format_rows(gw.get_status_codes(date_from, date_to))
        elif method == "top_countries":
            result = _format_rows(gw.get_top_countries(date_from, date_to, limit))
        elif method == "top_paths":
            result = _format_rows(gw.get_top_paths(date_from, date_to, limit))
        elif method == "threat_summary":
            result = _format_summary(gw.get_threat_summary(date_from, date_to))
        elif method == "content_types":
            result = _format_rows(gw.get_content_types(date_from, date_to))
        else:
            result = f"Неизвестный метод: {method}"

        return {"result": result}

    methods_desc = "\n".join(f"- {k}: {v}" for k, v in _CLOUDFLARE_METHODS.items())

    return Tool(
        name="cloudflare",
        description=(
            "Cloudflare — ИНФРАСТРУКТУРА и серверная нагрузка republicmag.io. "
            "Все HTTP-запросы (включая ботов, API, статику). Используй для вопросов про "
            "нагрузку, географию запросов, безопасность, кеширование, ошибки сервера.\n" + methods_desc
        ),
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
                "limit": {"type": "integer", "description": "Количество результатов (по умолчанию 20)"},
            },
            "required": ["method", "date_from", "date_to"],
        },
        fn=fn,
        permissions={"*": {"admin"}, "editorial_group": {"*"}},
        nl_routable=False,
        conversational=True,
    )
