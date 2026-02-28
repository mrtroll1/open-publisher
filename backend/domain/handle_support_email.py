"""Use case: draft a support response for an incoming email."""

from __future__ import annotations

import logging
from pathlib import Path

from common.models import IncomingEmail, SupportDraft
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway

logger = logging.getLogger(__name__)

_KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent.parent / "knowledge"


class HandleSupportEmail:
    """Read an incoming email, draft a response using the knowledge base."""

    def __init__(self):
        self._gemini = GeminiGateway()

    def execute(self, email: IncomingEmail) -> SupportDraft:
        knowledge = self._load_knowledge()
        email_text = f"From: {email.from_addr}\nSubject: {email.subject}\n\n{email.body}"
        draft = self._gemini.draft_support_response(email_text, knowledge)
        logger.info("Drafted support response for %s (uid=%s)", email.from_addr, email.uid)
        return SupportDraft(email=email, draft_reply=draft)

    _KNOWLEDGE_FILES = ["base.md", "tech-support.md"]

    @classmethod
    def _load_knowledge(cls) -> str:
        parts = []
        for name in cls._KNOWLEDGE_FILES:
            path = _KNOWLEDGE_DIR / name
            if path.exists():
                parts.append(path.read_text(encoding="utf-8"))
            else:
                logger.warning("Knowledge file not found: %s", path)
        return "\n\n---\n\n".join(parts)
