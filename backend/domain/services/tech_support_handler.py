"""Channel-independent tech support: context gathering + LLM draft replies."""

from __future__ import annotations

import json
import logging
import time
import uuid

from backend.domain.services import compose_request
from backend.domain.services.support_user_lookup import SupportUserLookup
from backend.infrastructure.gateways.db_gateway import DbGateway
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from backend.infrastructure.gateways.repo_gateway import RepoGateway
from common.models import IncomingEmail, SupportDraft

logger = logging.getLogger(__name__)


class TechSupportHandler:
    """Context gathering + LLM draft replies for tech support. No email sending."""

    def __init__(self, gemini: GeminiGateway | None = None, user_lookup: SupportUserLookup | None = None, db: DbGateway | None = None):
        self._gemini = gemini or GeminiGateway()
        self._user_lookup = user_lookup or SupportUserLookup()
        RepoGateway().ensure_repos()
        self._db = db or DbGateway()
        self._db.init_schema()
        self._uid_thread: dict[str, str] = {}

    def draft_reply(self, email: IncomingEmail) -> SupportDraft:
        """Gather context and draft a reply. Channel-independent."""
        thread_id = self._db.find_thread(email.message_id, email.in_reply_to, email.subject)
        self._db.save_message(thread_id, email, "inbound")
        self._uid_thread[email.uid] = thread_id
        history = self._db.get_thread_history(thread_id)

        email_text = email.as_text()
        user_data = self._fetch_user_data(email_text, email.reply_to or email.from_addr)

        thread_context = self._format_thread(history) if len(history) > 1 else ""
        context = "\n\n".join(filter(None, [user_data, thread_context]))

        prompt, model, _ = compose_request.support_email(email_text, context)
        result = self._gemini.call(prompt, model)
        can_answer = result.get("can_answer", False)
        logger.info("Drafted support response for %s (uid=%s, can_answer=%s)", email.from_addr, email.uid, can_answer)
        return SupportDraft(email=email, can_answer=can_answer, draft_reply=result.get("reply", ""))

    def save_outbound(self, uid: str, draft: SupportDraft) -> None:
        """Save sent reply to thread history."""
        thread_id = self._uid_thread.pop(uid, None)
        if not thread_id:
            return
        msg = self._build_thread_message(draft, f"outbound-{uuid.uuid4().hex}")
        self._db.save_message(thread_id, msg, "outbound")

    def discard(self, uid: str, draft: SupportDraft | None = None) -> None:
        """Clean up thread tracking for a skipped email."""
        thread_id = self._uid_thread.pop(uid, None)
        if draft and thread_id:
            msg = self._build_thread_message(draft, f"draft-rejected-{uuid.uuid4().hex}")
            self._db.save_message(thread_id, msg, "draft_rejected")

    @staticmethod
    def _build_thread_message(draft: SupportDraft, tag: str) -> IncomingEmail:
        em = draft.email
        return IncomingEmail(
            uid="",
            from_addr=em.to_addr,
            to_addr=em.reply_to or em.from_addr,
            subject=em.subject,
            body=draft.draft_reply,
            date="",
            message_id=f"<{tag}>",
            in_reply_to=em.message_id,
        )

    def _fetch_user_data(self, email_text: str, fallback_email: str) -> str:
        try:
            prompt, model, _ = compose_request.support_triage(email_text)
            t0 = time.time()
            result = self._gemini.call(prompt, model)
            latency_ms = int((time.time() - t0) * 1000)
            try:
                self._db.log_classification("SUPPORT_TRIAGE", model, prompt, json.dumps(result), latency_ms)
            except Exception:
                logger.warning("Failed to log classification for task=SUPPORT_TRIAGE", exc_info=True)
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

    @staticmethod
    def _format_thread(history: list[dict]) -> str:
        lines = ["## История переписки"]
        for msg in history:
            direction = "<<< входящее" if msg["direction"] == "inbound" else ">>> исходящее"
            lines.append(f"\n[{direction}] От: {msg['from_addr']} | {msg['date']}")
            lines.append(f"Тема: {msg['subject']}")
            lines.append(msg["body"] or "")
        return "\n".join(lines)
