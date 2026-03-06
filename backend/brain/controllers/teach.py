"""Teach controller — classify and store knowledge."""

from __future__ import annotations

from backend.brain.base_controller import BaseController, PassThroughPreparer
from backend.brain.dynamic.classify_teaching import ClassifyTeaching
from backend.commands.teach import TeachUseCase
from backend.infrastructure.memory.memory_service import MemoryService


class TeachController(BaseController):
    def __init__(self, classify: ClassifyTeaching, memory: MemoryService):
        super().__init__(PassThroughPreparer(), TeachUseCase(classify, memory))
