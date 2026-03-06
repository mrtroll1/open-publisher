from __future__ import annotations

from dataclasses import dataclass, field

from backend.brain.base_controller import BaseController


@dataclass
class Route:
    name: str
    controller: BaseController
    description: str
    examples: list[str] = field(default_factory=list)
    permissions: dict[str, set[str]] = field(default_factory=lambda: {"*": {"admin"}})
    slash_command: str | None = None
    nl_routable: bool = True


ROUTES: dict[str, Route] = {}


def register_route(route: Route) -> None:
    ROUTES[route.name] = route


ROUTE_DEFINITIONS: list[dict] = [
    {
        "name": "conversation",
        "description": "Свободный разговор, ответы на вопросы",
        "examples": ["что такое республика?", "расскажи о подписке", "про что статьи сегодня?"],
        "permissions": {"*": {"admin", "editor", "user"}},
        "slash_command": "nl",
    },
    {
        "name": "support",
        "description": "Техподдержка: вопросы о продукте, сайте, подписке",
        "examples": ["как отменить подписку?", "не работает оплата"],
        "permissions": {"*": {"admin", "editor", "user"}},
        "slash_command": "support",
    },
    {
        "name": "code",
        "description": "Работа с кодом, архитектура, баги",
        "examples": ["как нам скрыть лафки?", "можем ли мы имзенить дизайй рассылки?"],
        "permissions": {"*": {"admin"}},
        "slash_command": "code",
    },
    {
        "name": "health",
        "description": "Проверка доступности сервисов",
        "examples": ["лежит сайт", "всё ли работает?"],
        "permissions": {"*": {"admin", "editor", "user"}},
        "slash_command": "health",
    },
    {
        "name": "teach",
        "description": "Запомнить новое знание",
        "examples": ["запомни, что я сейчас скажу ..."],
        "permissions": {"*": {"admin"}, "editorial_group": {"admin", "editor"}},
        "slash_command": "teach",
    },
    {
        "name": "search",
        "description": "Поиск по базе знаний",
        "examples": ["найди информацию про ...", "что мы знаем о ..."],
        "permissions": {"*": {"admin"}, "editorial_group": {"admin", "editor"}},
        "slash_command": "search",
    },
    {
        "name": "invoice",
        "description": "Генерация счёта для автора",
        "examples": [],
        "permissions": {"*": {"admin"}},
        "slash_command": "generate",
    },
    {
        "name": "budget",
        "description": "Генерация бюджетной таблицы",
        "examples": [],
        "permissions": {"*": {"admin"}},
        "slash_command": "budget",
    },
    {
        "name": "ingest",
        "description": "Загрузка и обработка статей",
        "examples": [],
        "permissions": {"*": {"admin"}},
        "slash_command": "ingest_articles",
    },
    {
        "name": "inbox",
        "description": "Обработка входящей почты",
        "examples": [],
        "permissions": {"*": {"admin"}},
        "slash_command": None,
    },
]
