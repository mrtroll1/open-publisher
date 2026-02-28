"""Use case: draft a support response for an incoming email."""

from __future__ import annotations

import logging

from backend.domain import compose_request
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from common.models import IncomingEmail, SupportDraft

logger = logging.getLogger(__name__)


class HandleSupportEmail:
    """Read an incoming email, draft a response using the knowledge base."""

    def __init__(self):
        self._gemini = GeminiGateway()

    def execute(self, email: IncomingEmail) -> SupportDraft:
        email_text = f"From: {email.from_addr}\nSubject: {email.subject}\n\n{email.body}"
        prompt, model, _ = compose_request.support_email(email_text, email.to_addr)
        result = self._gemini.call(prompt, model)
        draft = result.get("reply", "")
        logger.info("Drafted support response for %s (uid=%s)", email.from_addr, email.uid)
        return SupportDraft(email=email, draft_reply=draft)
