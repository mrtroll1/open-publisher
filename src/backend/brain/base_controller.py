"""Base use case class used by command implementations."""

from __future__ import annotations

from typing import Any

from backend.brain.tool import EnvContext, UserContext


class BaseUseCase:
    def execute(self, prepared: Any, env: EnvContext, user: UserContext) -> Any:
        raise NotImplementedError
