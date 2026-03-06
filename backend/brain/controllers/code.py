"""Code controller — runs Claude Code CLI."""

from __future__ import annotations

from backend.brain.base_controller import BaseController, BasePreparer
from backend.commands.code import RunClaudeCodeUseCase
from backend.commands.utils import parse_flags


class CodePreparer(BasePreparer):
    def prepare(self, input: str, env: dict, user: dict) -> dict:
        verbose, expert, text = parse_flags(input)
        return {"prompt": text, "verbose": verbose, "expert": expert, "mode": "explore"}


class CodeController(BaseController):
    def __init__(self):
        super().__init__(CodePreparer(), RunClaudeCodeUseCase())
