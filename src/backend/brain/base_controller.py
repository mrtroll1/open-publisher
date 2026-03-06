"""Base use case class used by command implementations."""

from __future__ import annotations

from typing import Any


class BaseUseCase:
    def execute(self, prepared: Any, env: dict, user: dict) -> Any:
        raise NotImplementedError
