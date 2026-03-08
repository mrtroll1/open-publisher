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
from backend.models import CONTRACTOR_CLASS_BY_TYPE

logger = logging.getLogger(__name__)


class RegistrationParser:
    def __init__(self):
        self._gemini = GeminiGateway()
        self._retriever = KnowledgeRetriever()

    def parse(self, text, contractor_type, collected=None, warnings=None):
        cls = CONTRACTOR_CLASS_BY_TYPE[contractor_type]
        context = self._build_context(collected, cls, warnings)
        prompt = self._build_prompt(cls.field_names_csv(), context, text)
        result = self._gemini.call(prompt)
        if "parse_error" not in result:
            result["_validation_id"] = self._log_parse(text, contractor_type, result)
        return result

    def translate_name(self, name_en):
        prompt = load_template("contractor/translate-name.md", {"NAME": name_en})
        t0 = time.time()
        result = self._gemini.call(prompt)
        latency_ms = int((time.time() - t0) * 1000)
        self._log_translation(prompt, result, latency_ms)
        return result.get("translated_name", "")

    def _build_context(self, collected, cls, warnings):
        if not collected:
            return ""
        filled = {k: v for k, v in collected.items() if v and not k.startswith("_")}
        missing = [f for f in cls.FIELD_META if f not in filled]
        return self._join_context_parts(filled, missing, warnings)

    def _join_context_parts(self, filled, missing, warnings):
        parts = []
        if filled:
            parts.append(f"\nУже получено: {json.dumps(filled, ensure_ascii=False)}")
        if missing:
            parts.append(f"\nЕщё не заполнены: {', '.join(missing)}")
        if warnings:
            header = ("\nСледующие поля имеют ошибки валидации, пользователь "
                      "скорее всего исправляет их. Объедини новый ввод с уже "
                      "собранными данными, чтобы получить исправленное значение:\n")
            parts.append(header + "\n".join(f"- {w}" for w in warnings))
        return "".join(parts)

    def _build_prompt(self, fields_csv, context, text):
        knowledge = (self._retriever.get_domain_context("contractor")
                     + "\n\n" + self._retriever.retrieve_full_domain("contractor"))
        prompt = load_template("contractor/contractor-parse.md", {
            "FIELDS": fields_csv, "CONTEXT": context, "INPUT": text,
        })
        return (knowledge + "\n\n" + prompt) if knowledge else prompt

    def _log_parse(self, text, contractor_type, result):
        return DbGateway().save_message(
            text=text, type="system",
            metadata={"task": "payment_validation",
                      "contractor_type": contractor_type.value,
                      "parsed": result, "is_final": False},
        )

    def _log_translation(self, prompt, result, latency_ms):
        DbGateway().save_message(
            text=prompt, type="system",
            metadata={"task": "TRANSLATE_NAME", "model": GEMINI_MODEL_FAST,
                      "result": json.dumps(result), "latency_ms": latency_ms},
        )
