"""Classifies incoming messages and manages approval workflows."""

from __future__ import annotations

import json
import logging
import time

from backend.domain.services import compose_request
from backend.domain.services.tech_support_handler import TechSupportHandler
from backend.infrastructure.repositories.postgres import DbGateway
from backend.infrastructure.gateways.email_gateway import EmailGateway
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from common.config import CHIEF_EDITOR_EMAIL, EMAIL_ADDRESS, SUPPORT_ADDRESSES
from common.models import EditorialItem, IncomingEmail, PendingItem, SupportDraft

logger = logging.getLogger(__name__)


class InboxService:
    """Classifies incoming messages and manages approval workflows."""

    def __init__(self, tech_support: TechSupportHandler | None = None, gemini: GeminiGateway | None = None, email_gw: EmailGateway | None = None, db: DbGateway | None = None):
        self._tech_support = tech_support or TechSupportHandler()
        self._gemini = gemini or GeminiGateway()
        self._email_gw = email_gw or EmailGateway()
        self._db = db or DbGateway()
        self._pending_support: dict[str, SupportDraft] = {}
        self._pending_editorial: dict[str, EditorialItem] = {}

    # --- Processing ---

    def process(self, email: IncomingEmail) -> PendingItem | None:
        """Classify an email and route to the right handler."""
        category = self._classify(email)
        if category == "tech_support":
            return self._handle_support(email)
        elif category == "editorial":
            return self._handle_editorial(email)
        return None

    def _classify(self, email: IncomingEmail) -> str:
        if email.to_addr in SUPPORT_ADDRESSES:
            return "tech_support"
        if email.to_addr == EMAIL_ADDRESS:
            return self._llm_classify(email)
        return "ignore"

    def _llm_classify(self, email: IncomingEmail) -> str:
        prompt, model, _ = compose_request.inbox_classify(email.as_text())
        t0 = time.time()
        result = self._gemini.call(prompt, model)
        latency_ms = int((time.time() - t0) * 1000)
        try:
            self._db.log_classification("INBOX_CLASSIFY", model, prompt, json.dumps(result), latency_ms)
        except Exception:
            logger.warning("Failed to log classification for task=INBOX_CLASSIFY", exc_info=True)
        category = result.get("category", "ignore")
        logger.info("LLM classified email from %s as %s", email.from_addr, category)
        return category

    def _handle_support(self, email: IncomingEmail) -> PendingItem | None:
        if email.uid in self._pending_support:
            return None
        draft = self._tech_support.draft_reply(email)
        decision_id = self._db.create_email_decision(
            task="SUPPORT_ANSWER", channel="EMAIL",
            input_message_ids=[email.message_id],
        )
        draft.decision_id = decision_id
        self._pending_support[email.uid] = draft
        return PendingItem(category="tech_support", uid=email.uid, draft=draft)

    def _handle_editorial(self, email: IncomingEmail) -> PendingItem | None:
        if not CHIEF_EDITOR_EMAIL:
            return None
        prompt, model, _ = compose_request.editorial_assess(email.as_text())
        t0 = time.time()
        result = self._gemini.call(prompt, model)
        latency_ms = int((time.time() - t0) * 1000)
        try:
            self._db.log_classification("EDITORIAL_ASSESS", model, prompt, json.dumps(result), latency_ms)
        except Exception:
            logger.warning("Failed to log classification for task=EDITORIAL_ASSESS", exc_info=True)
        if not result.get("forward", False):
            return None
        item = EditorialItem(email=email, reply_to_sender=result.get("reply", ""))
        decision_id = self._db.create_email_decision(
            task="ARTICLE_APPROVAL", channel="EMAIL",
            input_message_ids=[email.message_id],
        )
        item.decision_id = decision_id
        self._pending_editorial[email.uid] = item
        return PendingItem(category="editorial", uid=email.uid, editorial=item)

    # --- Approval: tech support ---

    def approve_support(self, uid: str) -> SupportDraft | None:
        draft = self._pending_support.pop(uid, None)
        if not draft:
            return None
        if draft.decision_id:
            self._db.update_email_decision_output(draft.decision_id, draft.draft_reply)
            self._db.update_email_decision(draft.decision_id, "APPROVED", decided_by="admin")
        em = draft.email
        self._email_gw.send_reply(
            em.reply_to or em.from_addr, em.subject,
            draft.draft_reply, em.message_id, from_addr=em.to_addr,
        )
        self._email_gw.mark_read(uid)
        self._tech_support.save_outbound(uid, draft)
        return draft

    def update_and_approve_support(self, uid: str, new_reply: str) -> SupportDraft | None:
        draft = self._pending_support.get(uid)
        if not draft:
            return None
        draft.draft_reply = new_reply
        return self.approve_support(uid)

    def skip_support(self, uid: str) -> None:
        draft = self._pending_support.pop(uid, None)
        if draft and draft.decision_id:
            self._db.update_email_decision(draft.decision_id, "REJECTED", decided_by="admin")
        self._tech_support.discard(uid, draft=draft)

    def get_pending_support(self, uid: str) -> SupportDraft | None:
        return self._pending_support.get(uid)

    # --- Approval: editorial ---

    def approve_editorial(self, uid: str) -> EditorialItem | None:
        item = self._pending_editorial.pop(uid, None)
        if not item:
            return None
        if item.decision_id:
            self._db.update_email_decision(item.decision_id, "APPROVED", decided_by="admin")
        self._forward_to_editor(item.email)
        if item.reply_to_sender:
            self._email_gw.send_reply(
                item.email.reply_to or item.email.from_addr,
                f"Re: {item.email.subject}", item.reply_to_sender,
            )
        self._email_gw.mark_read(uid)
        return item

    def skip_editorial(self, uid: str) -> None:
        item = self._pending_editorial.pop(uid, None)
        if item and item.decision_id:
            self._db.update_email_decision(item.decision_id, "REJECTED", decided_by="admin")

    def get_pending_editorial(self, uid: str) -> EditorialItem | None:
        return self._pending_editorial.get(uid)

    # --- Email access (used by listener) ---

    def fetch_unread(self) -> list[IncomingEmail]:
        return self._email_gw.fetch_unread()

    def idle_wait(self, timeout: int = 300) -> bool:
        return self._email_gw.idle_wait(timeout)

    # --- Internal ---

    def _forward_to_editor(self, email: IncomingEmail) -> None:
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
