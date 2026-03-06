"""Support controller — tech support with flag parsing."""

from __future__ import annotations

from backend.brain.base_controller import BaseController, BasePreparer, GenAIUseCase
from backend.commands.utils import parse_flags


class SupportPreparer(BasePreparer):
    def prepare(self, input: str, env: dict, user: dict):
        verbose, expert, text = parse_flags(input)
        return {"question": text, "verbose": verbose, "expert": expert}


class SupportController(BaseController):
    def __init__(self, tech_support):
        super().__init__(SupportPreparer(), GenAIUseCase(tech_support))
