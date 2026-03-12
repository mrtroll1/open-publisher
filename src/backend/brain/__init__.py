from __future__ import annotations

from typing import Any

from backend.brain.authorizer import Authorizer
from backend.brain.router import Router
from backend.brain.tool import TOOLS


class Brain:
    def __init__(self, authorizer: Authorizer, router: Router,
                 conversation_fn=None):
        self.authorizer = authorizer
        self.router = router
        self._conversation_fn = conversation_fn

    def process(self, input: str, environment_id: str, user_id: str, **kwargs) -> Any:
        progress = kwargs.get("progress")
        if progress:
            progress.emit("authorize", "Авторизация")
        auth = self.authorizer.authorize(environment_id, user_id)
        if progress:
            progress.emit("route", "Классифицирую запрос")
        tool = self.router.route(input, auth.tools)
        if tool is None:
            # Conversation mode — ReAct loop with conversational tools
            return self._conversation_fn(input, auth, **kwargs)
        if progress:
            progress.emit("tool", f"Вызываю {tool.name}")
            auth.ctx.progress = progress
        return tool.execute({"input": input}, auth.ctx)

    def process_command(self, command: str, args: str, environment_id: str, user_id: str) -> Any:
        auth = self.authorizer.authorize(environment_id, user_id)
        tool = TOOLS[command]
        return tool.execute({"input": args}, auth.ctx)
