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
        fallback_email = context.get("from_addr", "")
        thread_context = context.get("thread_context", "")

        # Step 1: triage — determine what user data is needed
        triage_knowledge = self._retriever.retrieve_full_domain("support_triage")
        triage_prompt = load_template("email/support-triage.md", {
            "KNOWLEDGE": triage_knowledge,
            "EMAIL": input,
        })
        triage_result = self._gemini.call(triage_prompt, GEMINI_MODEL_FAST)

        needs = triage_result.get("needs", [])
        lookup_email = triage_result.get("lookup_email") or fallback_email

        # Fetch user data if triage determined it's needed
        user_data = ""
        if needs and lookup_email:
            user_data = self._user_lookup.fetch_and_format(lookup_email, needs)

        # Step 2: draft reply
        combined_context = "\n\n".join(filter(None, [user_data, thread_context]))
        knowledge = (self._retriever.get_domain_context("tech_support")
                     + "\n\n"
                     + self._retriever.retrieve(input, domain="tech_support", limit=5))
        draft_prompt = load_template("email/support-email.md", {
            "KNOWLEDGE": knowledge,
            "USER_DATA": combined_context,
            "EMAIL": input,
        })
        draft_result = self._gemini.call(draft_prompt, GEMINI_MODEL_SMART)

        return {
            "reply": draft_result.get("reply", ""),
            "can_answer": draft_result.get("can_answer", False),
            "needs": needs,
            "lookup_email": lookup_email,
        }

    def _pick_template(self, _input: str, _context: dict) -> str:
        return "email/support-email.md"

    def _build_context(self, _input: str, _context: dict) -> dict:
        return {}

    def _parse_response(self, raw: dict) -> dict:
        return {"reply": raw.get("reply", "")}
