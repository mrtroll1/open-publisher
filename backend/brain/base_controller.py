from __future__ import annotations

from typing import Any


class BasePreparer:
    def prepare(self, input: str, env: dict, user: dict) -> Any:
        raise NotImplementedError


class PassThroughPreparer(BasePreparer):
    def prepare(self, input: str, env: dict, user: dict) -> str:
        return input


class BaseUseCase:
    def execute(self, prepared: Any, env: dict, user: dict) -> Any:
        raise NotImplementedError


class BaseController:
    def __init__(self, preparer: BasePreparer, use_case: BaseUseCase):
        self.preparer = preparer
        self.use_case = use_case

    def execute(self, input: str, env: dict, user: dict) -> Any:
        prepared = self.preparer.prepare(input, env, user)
        return self.use_case.execute(prepared, env, user)
