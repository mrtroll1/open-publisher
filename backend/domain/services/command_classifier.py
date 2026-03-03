"""Command classifier — maps natural language text to bot commands via LLM."""

from __future__ import annotations

from dataclasses import dataclass

from backend.domain.services import compose_request
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway


@dataclass
class ClassifiedCommand:
    command: str
    args: str


@dataclass
class ClassificationResult:
    classified: ClassifiedCommand | None
    reply: str


class CommandClassifier:

    def __init__(self, gemini: GeminiGateway):
        self._gemini = gemini

    def classify(self, text: str, available_commands: dict[str, str]) -> ClassificationResult:
        commands_description = "\n".join(
            f"- **{name}** — {desc}" for name, desc in available_commands.items()
        )
        prompt, model, _ = compose_request.classify_command(text, commands_description)
        result = self._gemini.call(prompt, model, task="COMMAND_CLASSIFY")
        command = result.get("command")
        if not command or command not in available_commands:
            return ClassificationResult(classified=None, reply=result.get("reply", ""))
        return ClassificationResult(
            classified=ClassifiedCommand(command=command, args=result.get("args", "")),
            reply="",
        )
