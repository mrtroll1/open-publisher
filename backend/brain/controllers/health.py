"""Health controller — service healthchecks."""

from __future__ import annotations

from backend.brain.base_controller import BaseController, PassThroughPreparer
from backend.commands.check_health import CheckHealthUseCase


class HealthController(BaseController):
    def __init__(self):
        super().__init__(PassThroughPreparer(), CheckHealthUseCase())
