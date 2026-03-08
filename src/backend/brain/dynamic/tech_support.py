from __future__ import annotations

import logging

from backend.brain.base_genai import BaseGenAI
from backend.brain.prompt_loader import load_template
from backend.config import GEMINI_MODEL_FAST, GEMINI_MODEL_SMART
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from backend.infrastructure.memory.retriever import KnowledgeRetriever
from backend.infrastructure.memory.user_lookup import SupportUserLookup
from backend.infrastructure.repositories.postgres import DbGateway

logger = logging.getLogger(__name__)


class TechSupport(BaseGenAI):

    def __init__(self, gemini: GeminiGateway, retriever: KnowledgeRetriever,
                 db: DbGateway, user_lookup: SupportUserLookup | None = None):
        super().__init__(gemini)
        self._retriever = retriever
        self._db = db
        self._user_lookup = user_lookup or SupportUserLookup()

    def run(self, input: str, context: dict, *, _depth: int = 0) -> dict:
        triage = self._triage(input)
        user_data = self._fetch_user_data(triage, context.get("from_addr", ""))
        draft = self._draft_reply(input, user_data, context.get("thread_context", ""))
        return {
            "reply": draft.get("reply", ""),
            "can_answer": draft.get("can_answer", False),
            "needs": triage.get("needs", []),
            "lookup_email": triage.get("lookup_email", ""),
        }

    def _triage(self, input: str) -> dict:
        knowledge = self._retriever.retrieve_full_domain("support_triage")
        prompt = load_template("email/support-triage.md", {"KNOWLEDGE": knowledge, "EMAIL": input})
        return self._gemini.call(prompt, GEMINI_MODEL_FAST)

    def _fetch_user_data(self, triage: dict, fallback_email: str) -> str:
        needs = triage.get("needs", [])
        lookup_email = triage.get("lookup_email") or fallback_email
        if not needs or not lookup_email:
            return ""
        return self._user_lookup.fetch_and_format(lookup_email, needs)

    def _draft_reply(self, input: str, user_data: str, thread_context: str) -> dict:
        combined_context = "\n\n".join(filter(None, [user_data, thread_context]))
        knowledge = (self._retriever.get_domain_context("tech_support")
                     + "\n\n"
                     + self._retriever.retrieve(input, domain="tech_support", limit=5))
        prompt = load_template("email/support-email.md", {
            "KNOWLEDGE": knowledge, "USER_DATA": combined_context, "EMAIL": input,
        })
        return self._gemini.call(prompt, GEMINI_MODEL_SMART)

    def _pick_template(self, _input: str, _context: dict) -> str:
        return "email/support-email.md"

    def _build_context(self, _input: str, _context: dict) -> dict:
        return {}

    def _parse_response(self, raw: dict) -> dict:
        return {"reply": raw.get("reply", "")}
