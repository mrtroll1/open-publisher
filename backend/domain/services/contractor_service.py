"""Contractor registration business logic.

Sync functions extracted from telegram_bot/handlers/contractor_handlers.py.
Handlers call these via asyncio.to_thread().
"""

from __future__ import annotations

import json
import logging

from backend import (
    next_contractor_id,
    parse_contractor_data,
    pop_random_secret_code,
    save_contractor,
    translate_name_to_russian,
)
from backend.infrastructure.repositories.postgres import DbGateway
from common.models import CONTRACTOR_CLASS_BY_TYPE, Contractor, ContractorType

logger = logging.getLogger(__name__)


def parse_registration_data(
    text: str,
    contractor_type: ContractorType,
    collected: dict | None = None,
    warnings: list[str] | None = None,
) -> dict:
    """Parse contractor data from free-form text using LLM and log to DB.

    Returns the parsed result dict. On success, includes '_validation_id'.
    """
    cls = CONTRACTOR_CLASS_BY_TYPE[contractor_type]
    fields = cls.field_names_csv()

    context = ""
    if collected:
        filled = {k: v for k, v in collected.items() if v and not k.startswith("_")}
        missing = [f for f in cls.FIELD_META if f not in filled]
        if filled:
            context += f"\nУже получено: {json.dumps(filled, ensure_ascii=False)}"
        if missing:
            context += f"\nЕщё не заполнены: {', '.join(missing)}"
        if warnings:
            context += (
                "\nСледующие поля имеют ошибки валидации, пользователь "
                "скорее всего исправляет их. Объедини новый ввод с уже "
                "собранными данными, чтобы получить исправленное значение:\n"
                + "\n".join(f"- {w}" for w in warnings)
            )

    result = parse_contractor_data(text, fields, context)

    if "parse_error" not in result:
        try:
            vid = DbGateway().log_payment_validation(
                contractor_id="", contractor_type=contractor_type.value,
                input_text=text, parsed_json=json.dumps(result, ensure_ascii=False),
            )
            result["_validation_id"] = vid
        except Exception:
            logger.warning("Failed to log payment validation", exc_info=True)

    return result


def create_contractor(
    collected: dict, contractor_type: ContractorType,
    telegram_id: str, contractors: list[Contractor],
) -> tuple[Contractor | None, str]:
    """Build and save a new contractor from registration data.

    Returns (contractor, secret_code).
    """
    try:
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
    except Exception as e:
        logger.error("Failed to auto-save contractor: %s", e)
        return None, ""


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


def translate_contractor_name(name_en: str) -> str:
    """Translate an English name to Russian."""
    return translate_name_to_russian(name_en)
