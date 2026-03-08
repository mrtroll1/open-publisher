"""Contractor creation."""

from __future__ import annotations

import logging

from backend.infrastructure.repositories.sheets.contractor_repo import (
    next_contractor_id,
    pop_random_secret_code,
    save_contractor,
)
from backend.models import CONTRACTOR_CLASS_BY_TYPE

logger = logging.getLogger(__name__)


class ContractorFactory:
    def create(self, collected, contractor_type, telegram_id, contractors):
        cls = CONTRACTOR_CLASS_BY_TYPE[contractor_type]
        cid = next_contractor_id(contractors)
        code = pop_random_secret_code()
        kwargs = self._build_kwargs(collected, cls, telegram_id, cid, code)
        contractor = cls(**kwargs)
        save_contractor(contractor)
        logger.info("Auto-saved new contractor %s (%s)", cid, contractor.display_name)
        return contractor, code

    def _build_kwargs(self, collected, cls, telegram_id, cid, code):
        kwargs = dict(
            id=cid, aliases=collected.get("aliases", []), email=collected.get("email", ""),
            bank_name=collected.get("bank_name", ""), bank_account=collected.get("bank_account", ""),
            telegram=telegram_id, secret_code=code,
        )
        for field in cls.FIELD_META:
            if field not in kwargs:
                kwargs[field] = collected.get(field, "")
        return kwargs

    def check_complete(self, collected, required_fields):
        missing = {
            field: label
            for field, label in required_fields.items()
            if not collected.get(field, "").strip()
        }
        return (not missing, missing)
