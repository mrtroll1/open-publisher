"""Teach — classify input and store as knowledge."""

from __future__ import annotations

from typing import Any

from backend.brain.base_controller import BaseController, BaseUseCase, PassThroughPreparer
from backend.brain.dynamic.classify_teaching import ClassifyTeaching
from backend.infrastructure.memory.memory_service import MemoryService


class TeachUseCase(BaseUseCase):
    def __init__(self, classify: ClassifyTeaching, memory: MemoryService):
        self._classify = classify
        self._memory = memory

    def execute(self, prepared: Any, env: dict, user: dict) -> Any:
        result = self._classify.run(prepared, {})
        entry_id = self._memory.teach(prepared, domain=result["domain"], tier=result["tier"])
        return {"entry_id": entry_id, "domain": result["domain"], "tier": result["tier"]}


def create_teach_controller(classify: ClassifyTeaching, memory: MemoryService) -> BaseController:
    return BaseController(PassThroughPreparer(), TeachUseCase(classify, memory))
