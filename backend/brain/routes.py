from __future__ import annotations

from dataclasses import dataclass, field

from backend.brain.base_controller import BaseController


@dataclass
class Route:
    name: str
    controller: BaseController
    description: str
    examples: list[str] = field(default_factory=list)
    permissions: set[str] = field(default_factory=lambda: {"admin"})
    slash_command: str | None = None


ROUTES: dict[str, Route] = {}


def register_route(route: Route) -> None:
    ROUTES[route.name] = route
