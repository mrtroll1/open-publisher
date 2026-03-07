"""Inbox — approval workflow state and deterministic methods.

LLM classify/assess stays in brain/dynamic.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.brain.base_controller import BaseUseCase
from backend.brain.dynamic.assess_editorial import AssessEditorial
from backend.brain.dynamic.classify_inbox import ClassifyInbox
from backend.commands.draft_support import TechSupportHandler
from backend.config import CHIEF_EDITOR_EMAIL, SUPPORT_ADDRESSES
from backend.infrastructure.gateways.email_gateway import EmailGateway
from backend.infrastructure.repositories.postgres import DbGateway
from backend.models import EditorialItem, InboxCategory, IncomingEmail, PendingItem, SupportDraft

logger = logging.getLogger(__name__)


class InboxWorkflow:
    """Approval workflow state and deterministic routing for inbox items."""

    def __init__(self, tech_support: TechSupportHandler | None = None,
                 email_gw: EmailGateway | None = None, db: DbGateway | None = None,
                 classifier: ClassifyInbox | None = None,
                 assessor: AssessEditorial | None = None):
        self._tech_support = tech_support or TechSupportHandler()
        self._email_gw = email_gw or EmailGateway()
        self._db = db or DbGateway()
        self._classifier = classifier
        self._assessor = assessor
        self._pending_support: dict[str, SupportDraft] = {}
        self._pending_editorial: dict[str, EditorialItem] = {}

    # --- Full process flow ---

    def process(self, email: IncomingEmail) -> PendingItem | None:
        """Classify and handle an incoming email. Returns pending item or None."""
        category = self.classify_by_address(email)
        if category == "unknown" and self._classifier:
            result = self._classifier.run(email.as_text(), {})
            category = result.get("category", "ignore")
        if category == InboxCategory.TECH_SUPPORT:
            return self._handle_support(email)
        if category == InboxCategory.EDITORIAL:
            return self._handle_editorial(email)
        return None

    def _handle_support(self, email: IncomingEmail) -> PendingItem | None:
        if email.uid in self._pending_support:
            return None
        draft = self._tech_support.draft_reply(email)
        return self.register_support_draft(email, draft)

    def _handle_editorial(self, email: IncomingEmail) -> PendingItem | None:
        if not CHIEF_EDITOR_EMAIL or not self._assessor:
            return None
        result = self._assessor.run(email.as_text(), {})
        if not result.get("forward", False):
            return None
        item = EditorialItem(email=email, reply_to_sender=result.get("reply", ""))
        return self.register_editorial(email, item)

    # --- Deterministic classification ---

    def classify_by_address(self, email: IncomingEmail) -> str:
        """Rule-based classification by recipient address."""
        if email.to_addr in SUPPORT_ADDRESSES:
            return InboxCategory.TECH_SUPPORT
        return "unknown"

    # --- Support handling (deterministic parts) ---

    def register_support_draft(self, email: IncomingEmail, draft: SupportDraft) -> PendingItem:
        decision_id = self._db.save_message(
            text=draft.draft_reply, environment="email", type="system",
            metadata={"task": "SUPPORT_ANSWER", "status": "PENDING",
                      "input_message_ids": [email.message_id]},
        )
        draft.decision_id = decision_id
        self._pending_support[email.uid] = draft
        return PendingItem(category=InboxCategory.TECH_SUPPORT, uid=email.uid, draft=draft)

    def is_support_pending(self, uid: str) -> bool:
        return uid in self._pending_support

    # --- Editorial handling (deterministic parts) ---

    def register_editorial(self, email: IncomingEmail, item: EditorialItem) -> PendingItem:
        decision_id = self._db.save_message(
            text=item.reply_to_sender or "", environment="email", type="system",
            metadata={"task": "ARTICLE_APPROVAL", "status": "PENDING",
                      "input_message_ids": [email.message_id]},
        )
        item.decision_id = decision_id
        self._pending_editorial[email.uid] = item
        return PendingItem(category=InboxCategory.EDITORIAL, uid=email.uid, editorial=item)

    # --- Approval: tech support ---

    def approve_support(self, uid: str) -> SupportDraft | None:
        draft = self._pending_support.pop(uid, None)
        if not draft:
            return None
        if draft.decision_id:
            self._db.update_metadata(draft.decision_id, {"status": "APPROVED", "decided_by": "admin", "output": draft.draft_reply})
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
            self._db.update_metadata(draft.decision_id, {"status": "REJECTED", "decided_by": "admin"})
        self._tech_support.discard(uid, draft=draft)

    def get_pending_support(self, uid: str) -> SupportDraft | None:
        return self._pending_support.get(uid)

    # --- Approval: editorial ---

    def approve_editorial(self, uid: str) -> EditorialItem | None:
        item = self._pending_editorial.pop(uid, None)
        if not item:
            return None
        if item.decision_id:
            self._db.update_metadata(item.decision_id, {"status": "APPROVED", "decided_by": "admin"})
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
            self._db.update_metadata(item.decision_id, {"status": "REJECTED", "decided_by": "admin"})

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
    def __init__(self, classifier: ClassifyInbox, workflow: InboxWorkflow):
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


