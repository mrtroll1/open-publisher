from __future__ import annotations

from typing import Any

from backend.brain.base_genai import BaseGenAI


class BasePreparer:
    def prepare(self, input: str, env: dict, user: dict) -> Any:
        raise NotImplementedError


class PassThroughPreparer(BasePreparer):
    def prepare(self, input: str, env: dict, user: dict) -> str:
        return input


class BaseUseCase:
    def execute(self, prepared: Any, env: dict, user: dict) -> Any:
        raise NotImplementedError


class GenAIUseCase(BaseUseCase):
    def __init__(self, genai: BaseGenAI):
        self._genai = genai

    def execute(self, prepared: Any, env: dict, user: dict) -> Any:
        return self._genai.run(prepared, {"env": env, "user": user})


class StubUseCase(BaseUseCase):
    """Placeholder for unimplemented controllers."""
    def __init__(self, message: str = "Not implemented yet"):
        self._message = message

    def execute(self, prepared: Any, env: dict, user: dict) -> Any:
        return {"status": "stub", "message": self._message}


class BaseController:
    def __init__(self, preparer: BasePreparer, use_case: BaseUseCase):
        self.preparer = preparer
        self.use_case = use_case

    def execute(self, input: str, env: dict, user: dict, **kwargs) -> Any:
        prepared = self.preparer.prepare(input, env, user)
        return self.use_case.execute(prepared, env, user)
