"""Service: email support lifecycle — fetch, draft, approve, skip."""

from __future__ import annotations

import logging
import uuid

from backend.domain import compose_request
from backend.domain.support_user_lookup import SupportUserLookup
from backend.infrastructure.gateways.db_gateway import DbGateway
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
        self._db = DbGateway()
        self._db.init_schema()
        self._pending: dict[str, SupportDraft] = {}
        self._non_support: list[IncomingEmail] = []
        # Map uid → thread_id for saving outbound replies
        self._uid_thread: dict[str, str] = {}

    def wait_for_mail(self, timeout: int = 300) -> bool:
        """IMAP IDLE — block until new mail or timeout."""
        return self._email_gw.idle_wait(timeout)

    def fetch_new_drafts(self) -> list[SupportDraft]:
        """Fetch unread emails, filter by SUPPORT_ADDRESSES, draft replies."""
        emails = self._email_gw.fetch_unread()
        drafts = []
        non_support = []
        for em in emails:
            if em.to_addr not in SUPPORT_ADDRESSES:
                non_support.append(em)
                continue
            if em.uid in self._pending:
                continue
            draft = self._draft(em)
            self._pending[em.uid] = draft
            drafts.append(draft)
        self._non_support = non_support
        return drafts

    def fetch_non_support(self) -> list[IncomingEmail]:
        """Return non-support emails from the last fetch, clearing the buffer."""
        result = self._non_support
        self._non_support = []
        return result

    def approve(self, uid: str) -> SupportDraft | None:
        """Send the pending draft reply and mark as read."""
        draft = self._pending.pop(uid, None)
        if not draft:
            return None
        em = draft.email
        self._email_gw.send_reply(em.reply_to or em.from_addr, em.subject, draft.draft_reply, em.message_id, from_addr=em.to_addr)
        self._email_gw.mark_read(uid)
        self._save_outbound(uid, draft)
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
        self._uid_thread.pop(uid, None)

    def get_pending(self, uid: str) -> SupportDraft | None:
        return self._pending.get(uid)

    def _save_outbound(self, uid: str, draft: SupportDraft) -> None:
        thread_id = self._uid_thread.pop(uid, None)
        if not thread_id:
            return
        em = draft.email
        outbound = IncomingEmail(
            uid="",
            from_addr=em.to_addr,
            to_addr=em.reply_to or em.from_addr,
            subject=em.subject,
            body=draft.draft_reply,
            date="",
            message_id=f"<outbound-{uuid.uuid4().hex}>",
            in_reply_to=em.message_id,
        )
        self._db.save_message(thread_id, outbound, "outbound")

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
        # Thread tracking
        thread_id = self._db.find_thread(email.message_id, email.in_reply_to, email.subject)
        self._db.save_message(thread_id, email, "inbound")
        self._uid_thread[email.uid] = thread_id
        history = self._db.get_thread_history(thread_id)

        email_text = f"From: {email.from_addr}\nSubject: {email.subject}\n\n{email.body}"
        user_data = self._fetch_user_data(email_text, email.reply_to or email.from_addr)

        thread_context = self._format_thread(history) if len(history) > 1 else ""
        context = "\n\n".join(filter(None, [user_data, thread_context]))

        if context:
            prompt, model, _ = compose_request.support_email_with_context(email_text, context)
        else:
            prompt, model, _ = compose_request.support_email(email_text)
        result = self._gemini.call(prompt, model)
        can_answer = result.get("can_answer", False)
        logger.info("Drafted support response for %s (uid=%s, can_answer=%s)", email.from_addr, email.uid, can_answer)
        return SupportDraft(email=email, can_answer=can_answer, draft_reply=result.get("reply", ""))

    @staticmethod
    def _format_thread(history: list[dict]) -> str:
        lines = ["## История переписки"]
        for msg in history:
            direction = "<<< входящее" if msg["direction"] == "inbound" else ">>> исходящее"
            lines.append(f"\n[{direction}] От: {msg['from_addr']} | {msg['date']}")
            lines.append(f"Тема: {msg['subject']}")
            lines.append(msg["body"] or "")
        return "\n".join(lines)
