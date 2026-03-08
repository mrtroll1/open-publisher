"""Contractor registration — parsing and name translation."""

from __future__ import annotations

import json
import logging
import time

from backend.brain.prompt_loader import load_template
from backend.config import GEMINI_MODEL_FAST
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from backend.infrastructure.memory.retriever import KnowledgeRetriever
from backend.infrastructure.repositories.postgres import DbGateway
from backend.models import CONTRACTOR_CLASS_BY_TYPE, ContractorType

_gemini = GeminiGateway()
_retriever = KnowledgeRetriever()

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

    knowledge = _retriever.get_domain_context("contractor") + "\n\n" + _retriever.retrieve_full_domain("contractor")
    prompt = load_template("contractor/contractor-parse.md", {
        "FIELDS": fields,
        "CONTEXT": context,
        "INPUT": text,
    })
    if knowledge:
        prompt = knowledge + "\n\n" + prompt
    result = _gemini.call(prompt)

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
    prompt = load_template("contractor/translate-name.md", {"NAME": name_en})
    t0 = time.time()
    result = _gemini.call(prompt)
    latency_ms = int((time.time() - t0) * 1000)
    DbGateway().save_message(
        text=prompt, type="system",
        metadata={"task": "TRANSLATE_NAME", "model": GEMINI_MODEL_FAST,
                  "result": json.dumps(result), "latency_ms": latency_ms},
    )
    return result.get("translated_name", "")
