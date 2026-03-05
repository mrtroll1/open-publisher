"""Command classifier — maps natural language text to bot commands via LLM."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

from backend.domain.services import compose_request
from backend.infrastructure.repositories.postgres import DbGateway
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway

logger = logging.getLogger(__name__)


@dataclass
class ClassifiedCommand:
    command: str
    args: str


@dataclass
class ClassificationResult:
    classified: ClassifiedCommand | None
    reply: str


class CommandClassifier:

    def __init__(self, gemini: GeminiGateway, db: DbGateway | None = None):
        self._gemini = gemini
        self._db = db

    def classify(self, text: str, available_commands: dict[str, str], context: str = "") -> ClassificationResult:
        commands_description = "\n".join(
            f"- **{name}** — {desc}" for name, desc in available_commands.items()
        )
        prompt, model, _ = compose_request.classify_command(text, commands_description, context=context)
        t0 = time.time()
        result = self._gemini.call(prompt, model)
        latency_ms = int((time.time() - t0) * 1000)
        if self._db:
            try:
                self._db.log_classification("COMMAND_CLASSIFY", model, prompt, json.dumps(result), latency_ms)
            except Exception:
                logger.warning("Failed to log classification for task=COMMAND_CLASSIFY", exc_info=True)
        command = result.get("command")
        if not command or command not in available_commands:
            return ClassificationResult(classified=None, reply=result.get("reply", ""))
        return ClassificationResult(
            classified=ClassifiedCommand(command=command, args=result.get("args", "")),
            reply="",
        )
