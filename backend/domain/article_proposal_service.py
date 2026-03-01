"""Service: detect and forward article proposals from incoming emails."""

from backend.domain import compose_request
from backend.infrastructure.gateways.email_gateway import EmailGateway
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from common.config import CHIEF_EDITOR_EMAIL
from common.models import IncomingEmail


class ArticleProposalService:

    def __init__(self):
        self._gemini = GeminiGateway()
        self._email_gw = EmailGateway()

    def process_proposals(self, emails: list[IncomingEmail]) -> list[IncomingEmail]:
        """Judge each email with LLM, forward legit proposals. Returns list of forwarded emails."""
        if not CHIEF_EDITOR_EMAIL:
            return []
        forwarded = []
        for em in emails:
            if self._is_legit_proposal(em):
                self._forward(em)
                forwarded.append(em)
        return forwarded

    def _is_legit_proposal(self, email: IncomingEmail) -> bool:
        email_text = f"From: {email.from_addr}\nSubject: {email.subject}\n\n{email.body}"
        prompt, model, _ = compose_request.article_proposal_triage(email_text)
        result = self._gemini.call(prompt, model)
        return result.get("is_legit_proposal", False)

    def _forward(self, email: IncomingEmail) -> None:
        body = (
            f"Переслано автоматически.\n\n"
            f"От: {email.from_addr}\n"
            f"Тема: {email.subject}\n"
            f"Дата: {email.date}\n\n"
            f"{email.body}"
        )
        self._email_gw.send_reply(
            CHIEF_EDITOR_EMAIL,
            f"Fwd: {email.subject}",
            body,
        )
