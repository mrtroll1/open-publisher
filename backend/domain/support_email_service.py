"""Service: email support lifecycle — fetch, draft, approve, skip."""

from __future__ import annotations

import logging

from backend.domain import compose_request
from backend.domain.support_user_lookup import SupportUserLookup
from backend.infrastructure.gateways.email_gateway import EmailGateway
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from common.config import SUPPORT_ADDRESSES
from common.models import IncomingEmail, SupportDraft

logger = logging.getLogger(__name__)


class SupportEmailService:
    """Orchestrates the support email lifecycle. All methods are synchronous."""

    def __init__(self):
        self._email_gw = EmailGateway()
        self._gemini = GeminiGateway()
        self._user_lookup = SupportUserLookup()
        self._pending: dict[str, SupportDraft] = {}

    def wait_for_mail(self, timeout: int = 300) -> bool:
        """IMAP IDLE — block until new mail or timeout."""
        return self._email_gw.idle_wait(timeout)

    def fetch_new_drafts(self) -> list[SupportDraft]:
        """Fetch unread emails, filter by SUPPORT_ADDRESSES, draft replies."""
        emails = self._email_gw.fetch_unread()
        drafts = []
        for em in emails:
            if em.to_addr not in SUPPORT_ADDRESSES:
                continue
            if em.uid in self._pending:
                continue
            draft = self._draft(em)
            self._pending[em.uid] = draft
            drafts.append(draft)
        return drafts

    def approve(self, uid: str) -> SupportDraft | None:
        """Send the pending draft reply and mark as read."""
        draft = self._pending.pop(uid, None)
        if not draft:
            return None
        em = draft.email
        self._email_gw.send_reply(em.reply_to or em.from_addr, em.subject, draft.draft_reply, em.message_id, from_addr=em.to_addr)
        self._email_gw.mark_read(uid)
        return draft

    def update_and_approve(self, uid: str, new_reply: str) -> SupportDraft | None:
        """Update draft text, send, and mark as read."""
        draft = self._pending.get(uid)
        if not draft:
            return None
        draft.draft_reply = new_reply
        return self.approve(uid)

    def skip(self, uid: str) -> None:
        """Mark as read without replying."""
        self._email_gw.mark_read(uid)
        self._pending.pop(uid, None)

    def get_pending(self, uid: str) -> SupportDraft | None:
        return self._pending.get(uid)

    def _fetch_user_data(self, email_text: str, fallback_email: str) -> str:
        """Run triage LLM call; if data needed, fetch from APIs."""
        try:
            prompt, model, _ = compose_request.support_triage(email_text)
            result = self._gemini.call(prompt, model)
            needs = result.get("needs", [])
            lookup_email = result.get("lookup_email") or fallback_email
            logger.info("Support triage: needs=%s, lookup_email=%s", needs, lookup_email)
            if not needs or not lookup_email:
                return ""
            user_data = self._user_lookup.fetch_and_format(lookup_email, needs)
            logger.info("User data for %s:\n%s", lookup_email, user_data or "(empty)")
            return user_data
        except Exception as e:
            logger.error("Support triage/lookup failed: %s", e)
            return ""

    def _draft(self, email: IncomingEmail) -> SupportDraft:
        """Use compose_request + Gemini to draft a reply."""
        email_text = f"From: {email.from_addr}\nSubject: {email.subject}\n\n{email.body}"
        user_data = self._fetch_user_data(email_text, email.reply_to or email.from_addr)
        if user_data:
            prompt, model, _ = compose_request.support_email_with_context(email_text, user_data)
        else:
            prompt, model, _ = compose_request.support_email(email_text)
        result = self._gemini.call(prompt, model)
        can_answer = result.get("can_answer", False)
        logger.info("Drafted support response for %s (uid=%s, can_answer=%s)", email.from_addr, email.uid, can_answer)
        return SupportDraft(email=email, can_answer=can_answer, draft_reply=result.get("reply", ""))
