"""Contractor creation — deterministic parts. LLM parsing via brain/dynamic."""

from __future__ import annotations

import logging

from backend import (
    next_contractor_id,
    pop_random_secret_code,
    save_contractor,
)
from backend.models import CONTRACTOR_CLASS_BY_TYPE, Contractor, ContractorType

logger = logging.getLogger(__name__)


def create_contractor(
    collected: dict, contractor_type: ContractorType,
    telegram_id: str, contractors: list[Contractor],
) -> tuple[Contractor, str]:
    """Build and save a new contractor from registration data.

    Returns (contractor, secret_code).
    """
    cid = next_contractor_id(contractors)
    cls = CONTRACTOR_CLASS_BY_TYPE[contractor_type]
    code = pop_random_secret_code()

    kwargs = dict(
        id=cid,
        aliases=collected.get("aliases", []),
        email=collected.get("email", ""),
        bank_name=collected.get("bank_name", ""),
        bank_account=collected.get("bank_account", ""),
        telegram=telegram_id,
        secret_code=code,
    )
    for field in cls.FIELD_META:
        if field not in kwargs:
            kwargs[field] = collected.get(field, "")

    contractor = cls(**kwargs)
    save_contractor(contractor)
    logger.info("Auto-saved new contractor %s (%s)", cid, contractor.display_name)
    return contractor, code


def check_registration_complete(
    collected: dict, required_fields: dict[str, str],
) -> tuple[bool, dict[str, str]]:
    """Check whether all required fields are filled.

    Returns (is_complete, missing) where missing is {field: label}.
    """
    missing = {
        field: label
        for field, label in required_fields.items()
        if not collected.get(field, "").strip()
    }
    return (not missing, missing)
