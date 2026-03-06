from __future__ import annotations

from typing import Any

from backend.brain.authorizer import Authorizer
from backend.brain.router import Router
from backend.brain.routes import ROUTES


class Brain:
    def __init__(self, authorizer: Authorizer, router: Router):
        self.authorizer = authorizer
        self.router = router

    def process(self, input: str, environment_id: str, user_id: str, **kwargs) -> Any:
        auth = self.authorizer.authorize(environment_id, user_id)
        route = self.router.route(input, auth.routes)
        return route.controller.execute(input, auth.env, auth.user, **kwargs)

    def process_command(self, command: str, args: str, environment_id: str, user_id: str, **kwargs) -> Any:
        auth = self.authorizer.authorize(environment_id, user_id)
        route = ROUTES[command]
        return route.controller.execute(args, auth.env, auth.user, **kwargs)
