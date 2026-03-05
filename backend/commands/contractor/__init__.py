"""Contractor controllers — placeholder for complex create/validate/sync flow."""

from __future__ import annotations

from backend.brain.base_controller import BaseController, PassThroughPreparer, StubUseCase


def create_contractor_controller() -> BaseController:
    return BaseController(PassThroughPreparer(), StubUseCase("Contractor flow not yet wired"))
