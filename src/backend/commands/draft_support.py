"""Channel-independent tech support: context gathering + LLM draft replies."""

from __future__ import annotations

import json
import logging
import time
import uuid

from common.prompt_loader import load_template
from backend.infrastructure.memory.retriever import KnowledgeRetriever
from backend.infrastructure.memory.user_lookup import SupportUserLookup
from backend.infrastructure.repositories.postgres import DbGateway
from backend.infrastructure.repositories.postgres.message_repo import normalize_email_subject
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from backend.infrastructure.gateways.repo_gateway import RepoGateway
from common.models import IncomingEmail, SupportDraft

logger = logging.getLogger(__name__)


class TechSupportHandler:
    """Context gathering + LLM draft replies for tech support. No email sending."""

    def __init__(self, gemini: GeminiGateway | None = None,
                 user_lookup: SupportUserLookup | None = None,
                 db: DbGateway | None = None,
                 retriever: KnowledgeRetriever | None = None):
        self._gemini = gemini or GeminiGateway()
        self._user_lookup = user_lookup or SupportUserLookup()
        RepoGateway().ensure_repos()
        self._db = db or DbGateway()
        self._db.init_schema()
        self._retriever = retriever or KnowledgeRetriever()

    def draft_reply(self, email: IncomingEmail) -> SupportDraft:
        # Save inbound email as message, linking to thread via parent_id
        parent_id = self._db.find_email_parent(
            in_reply_to=email.in_reply_to, subject=email.subject,
        )
        sender = self._db.get_or_create_by_email(email.from_addr)
        msg_id = self._db.save_message(
            text=email.body, environment="email", type="user",
            user_id=sender["id"], parent_id=parent_id,
            metadata={
                "email_message_id": email.message_id,
                "from": email.from_addr, "to": email.to_addr,
                "subject": email.subject, "date": email.date,
                "in_reply_to": email.in_reply_to or "",
                "normalized_subject": normalize_email_subject(email.subject),
                "direction": "inbound", "uid": email.uid,
            },
        )

        # Get thread history for context
        history = self._db.get_thread_history(msg_id)

        email_text = email.as_text()
        user_data = self._fetch_user_data(email_text, email.reply_to or email.from_addr)

        thread_context = self._format_thread(history) if len(history) > 1 else ""
        context = "\n\n".join(filter(None, [user_data, thread_context]))

        knowledge = (self._retriever.get_domain_context("tech_support")
                     + "\n\n"
                     + self._retriever.retrieve(email_text, domain="tech_support", limit=5))
        prompt = load_template("email/support-email.md", {
            "KNOWLEDGE": knowledge,
            "USER_DATA": context,
            "EMAIL": email_text,
        })
        result = self._gemini.call(prompt, "gemini-3-flash-preview")
        can_answer = result.get("can_answer", False)
        logger.info("Drafted support response for %s (uid=%s, can_answer=%s)", email.from_addr, email.uid, can_answer)
        draft = SupportDraft(email=email, can_answer=can_answer, draft_reply=result.get("reply", ""))
        draft._inbound_msg_id = msg_id
        return draft

    def save_outbound(self, uid: str, draft: SupportDraft) -> None:
        inbound_id = getattr(draft, "_inbound_msg_id", None)
        if not inbound_id:
            return
        self._db.save_message(
            text=draft.draft_reply, environment="email", type="assistant",
            parent_id=inbound_id,
            metadata={
                "email_message_id": f"<outbound-{uuid.uuid4().hex}>",
                "from": draft.email.to_addr,
                "to": draft.email.reply_to or draft.email.from_addr,
                "subject": draft.email.subject,
                "direction": "outbound",
                "normalized_subject": normalize_email_subject(draft.email.subject),
            },
        )

    def discard(self, uid: str, draft: SupportDraft | None = None) -> None:
        if not draft:
            return
        inbound_id = getattr(draft, "_inbound_msg_id", None)
        if inbound_id:
            self._db.save_message(
                text=draft.draft_reply, environment="email", type="assistant",
                parent_id=inbound_id,
                metadata={
                    "email_message_id": f"<draft-rejected-{uuid.uuid4().hex}>",
                    "direction": "draft_rejected",
                    "normalized_subject": normalize_email_subject(draft.email.subject),
                },
            )

    def _fetch_user_data(self, email_text: str, fallback_email: str) -> str:
        try:
            triage_knowledge = self._retriever.retrieve_full_domain("support_triage")
            prompt = load_template("email/support-triage.md", {
                "KNOWLEDGE": triage_knowledge,
                "EMAIL": email_text,
            })
            t0 = time.time()
            result = self._gemini.call(prompt, "gemini-2.5-flash")
            latency_ms = int((time.time() - t0) * 1000)
            try:
                self._db.save_message(
                    text=prompt, environment="email", type="system",
                    metadata={"task": "SUPPORT_TRIAGE", "model": "gemini-2.5-flash",
                              "result": json.dumps(result), "latency_ms": latency_ms},
                )
            except Exception:
                logger.warning("Failed to log triage classification", exc_info=True)
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
            meta = msg.get("metadata") or {}
            direction = "<<< входящее" if meta.get("direction") == "inbound" else ">>> исходящее"
            from_addr = meta.get("from", "")
            date = meta.get("date", "")
            subject = meta.get("subject", "")
            lines.append(f"\n[{direction}] От: {from_addr} | {date}")
            lines.append(f"Тема: {subject}")
            lines.append(msg["text"] or "")
        return "\n".join(lines)
