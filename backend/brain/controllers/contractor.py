"""Contractor controller — placeholder for complex create/validate/sync flow."""

from __future__ import annotations

from backend.brain.base_controller import BaseController, PassThroughPreparer, StubUseCase


class ContractorController(BaseController):
    def __init__(self):
        super().__init__(PassThroughPreparer(), StubUseCase("Contractor flow not yet wired"))
