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
        auth = self.authorizer.authorize(environment_id, user_id)
        tool = self.router.route(input, auth.tools)
        if tool is None:
            # Conversation mode — ReAct loop with conversational tools
            return self._conversation_fn(input, auth, **kwargs)
        return tool.execute({"input": input}, auth.ctx)

    def process_command(self, command: str, args: str, environment_id: str, user_id: str, **kwargs) -> Any:
        auth = self.authorizer.authorize(environment_id, user_id)
        tool = TOOLS[command]
        return tool.execute({"input": args}, auth.ctx)
