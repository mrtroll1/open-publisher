"""Inbox — approval workflow state and deterministic methods.

LLM classify/assess stays in brain/dynamic.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.brain.base_controller import BaseController, BaseUseCase, PassThroughPreparer
from backend.brain.dynamic.inbox_classify import InboxClassify
from backend.commands.support_handler import TechSupportHandler
from backend.infrastructure.repositories.postgres import DbGateway
from backend.infrastructure.gateways.email_gateway import EmailGateway
from common.config import CHIEF_EDITOR_EMAIL, SUPPORT_ADDRESSES
from common.models import EditorialItem, IncomingEmail, PendingItem, SupportDraft

logger = logging.getLogger(__name__)


class InboxWorkflow:
    """Approval workflow state and deterministic routing for inbox items."""

    def __init__(self, tech_support: TechSupportHandler | None = None,
                 email_gw: EmailGateway | None = None, db: DbGateway | None = None):
        self._tech_support = tech_support or TechSupportHandler()
        self._email_gw = email_gw or EmailGateway()
        self._db = db or DbGateway()
        self._pending_support: dict[str, SupportDraft] = {}
        self._pending_editorial: dict[str, EditorialItem] = {}

    # --- Deterministic classification ---

    def classify_by_address(self, email: IncomingEmail) -> str:
        """Rule-based classification by recipient address."""
        if email.to_addr in SUPPORT_ADDRESSES:
            return "tech_support"
        return "unknown"

    # --- Support handling (deterministic parts) ---

    def register_support_draft(self, email: IncomingEmail, draft: SupportDraft) -> PendingItem:
        decision_id = self._db.create_email_decision(
            task="SUPPORT_ANSWER", channel="EMAIL",
            input_message_ids=[email.message_id],
        )
        draft.decision_id = decision_id
        self._pending_support[email.uid] = draft
        return PendingItem(category="tech_support", uid=email.uid, draft=draft)

    def is_support_pending(self, uid: str) -> bool:
        return uid in self._pending_support

    # --- Editorial handling (deterministic parts) ---

    def register_editorial(self, email: IncomingEmail, item: EditorialItem) -> PendingItem:
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


class InboxProcessUseCase(BaseUseCase):
    """Classify incoming email. Full orchestration (approve/reject) handled by InboxWorkflow."""
    def __init__(self, classifier: InboxClassify, workflow: InboxWorkflow):
        self._classifier = classifier
        self._workflow = workflow

    def execute(self, prepared: Any, env: dict, user: dict) -> Any:
        # Rule-based first
        rule_category = self._workflow.classify_by_address(prepared) if hasattr(prepared, "to_addr") else "unknown"
        if rule_category != "unknown":
            return {"category": rule_category, "source": "rules"}
        # Fall back to AI classification
        email_text = prepared.body if hasattr(prepared, "body") else str(prepared)
        result = self._classifier.run(email_text, {})
        return {"category": result.get("category", "unknown"), "reason": result.get("reason", ""), "source": "ai"}


def create_inbox_controller(classifier: InboxClassify, workflow: InboxWorkflow) -> BaseController:
    return BaseController(PassThroughPreparer(), InboxProcessUseCase(classifier, workflow))
