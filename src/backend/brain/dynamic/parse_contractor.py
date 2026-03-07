from __future__ import annotations

from backend.brain.base_genai import BaseGenAI
from backend.brain.prompt_loader import load_template
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from backend.infrastructure.memory.retriever import KnowledgeRetriever


class ParseContractor(BaseGenAI):

    def __init__(self, gemini: GeminiGateway, retriever: KnowledgeRetriever):
        super().__init__(gemini)
        self._retriever = retriever

    def _pick_template(self, _input: str, _context: dict) -> str:
        return "contractor/contractor-parse.md"

    def _build_context(self, input: str, context: dict) -> dict:
        fields_csv = context.get("fields", "")
        ctx = context.get("context", "")
        return {
            "FIELDS": fields_csv,
            "CONTEXT": ctx,
            "INPUT": input,
        }

    def run(self, input: str, context: dict, *, _depth: int = 0) -> dict:
        # Prepend domain knowledge to the prompt (matching compose_request pattern)
        knowledge = (self._retriever.get_domain_context("contractor")
                     + "\n\n"
                     + self._retriever.retrieve_full_domain("contractor"))

        template = self._pick_template(input, context)
        built_context = self._build_context(input, context)
        prompt = load_template(template, built_context)
        if knowledge:
            prompt = knowledge + "\n\n" + prompt

        raw = self._call_ai(prompt)
        return self._parse_response(raw)

    def _parse_response(self, raw: dict) -> dict:
        return raw
