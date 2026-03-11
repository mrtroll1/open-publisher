"""Contractor creation."""

from __future__ import annotations

import logging

from backend.infrastructure.repositories.sheets.contractor_repo import (
    delete_contractor_from_sheet,
    find_contractor_by_id,
    next_contractor_id,
    pop_random_secret_code,
    save_contractor,
    save_stub,
)
from backend.models import CONTRACTOR_CLASS_BY_TYPE, RoleCode, StubContractor

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

    def upgrade_from_stub(self, stub_id, collected, contractor_type, telegram_id, contractors):
        """Replace a stub with a full contractor, preserving ID and secret code."""
        stub = find_contractor_by_id(stub_id, contractors)
        delete_contractor_from_sheet(stub_id)
        if stub and stub.display_name:
            aliases = collected.get("aliases", [])
            if stub.display_name not in aliases:
                aliases.append(stub.display_name)
            collected["aliases"] = aliases
        cls = CONTRACTOR_CLASS_BY_TYPE[contractor_type]
        code = stub.secret_code if stub else ""
        kwargs = self._build_kwargs(collected, cls, telegram_id, stub_id, code)
        contractor = cls(**kwargs)
        save_contractor(contractor)
        logger.info("Upgraded stub %s to %s (%s)", stub_id, contractor_type.value, contractor.display_name)
        return contractor, code

    def create_stub(self, name, contractors):
        cid = next_contractor_id(contractors)
        code = pop_random_secret_code()
        stub = StubContractor(
            id=cid, name=name, aliases=[name],
            role_code=RoleCode.AUTHOR,
            email="", bank_name="", bank_account="",
            secret_code=code,
        )
        save_stub(stub)
        logger.info("Created stub contractor %s (%s)", cid, name)
        return stub, code

    def check_complete(self, collected, required_fields):
        missing = {
            field: label
            for field, label in required_fields.items()
            if not collected.get(field, "").strip()
        }
        return (not missing, missing)

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
