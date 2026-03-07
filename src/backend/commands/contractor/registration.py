"""Contractor registration — parsing and name translation."""

from __future__ import annotations

import json
import logging

from backend import parse_contractor_data, translate_name_to_russian
from backend.infrastructure.repositories.postgres import DbGateway
from backend.models import CONTRACTOR_CLASS_BY_TYPE, ContractorType

logger = logging.getLogger(__name__)


def parse_registration_data(
    text: str,
    contractor_type: ContractorType,
    collected: dict | None = None,
    warnings: list[str] | None = None,
) -> dict:
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
        vid = DbGateway().save_message(
            text=text, type="system",
            metadata={"task": "payment_validation",
                       "contractor_type": contractor_type.value,
                       "parsed": result, "is_final": False},
        )
        result["_validation_id"] = vid

    return result


def translate_contractor_name(name_en: str) -> str:
    return translate_name_to_russian(name_en)
