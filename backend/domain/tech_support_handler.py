"""Channel-independent tech support: context gathering + LLM draft replies."""

from __future__ import annotations

import logging
import uuid

from backend.domain import compose_request
from backend.domain.support_user_lookup import SupportUserLookup
from backend.infrastructure.gateways.db_gateway import DbGateway
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from backend.infrastructure.gateways.repo_gateway import RepoGateway
from common.models import IncomingEmail, SupportDraft

logger = logging.getLogger(__name__)


class TechSupportHandler:
    """Context gathering + LLM draft replies for tech support. No email sending."""

    def __init__(self):
        self._gemini = GeminiGateway()
        self._user_lookup = SupportUserLookup()
        self._repo_gw = RepoGateway()
        self._repo_gw.ensure_repos()
        self._db = DbGateway()
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
        code_context = self._fetch_code_context(email_text)

        thread_context = self._format_thread(history) if len(history) > 1 else ""
        context = "\n\n".join(filter(None, [user_data, thread_context, code_context]))

        if context:
            prompt, model, _ = compose_request.support_email_with_context(email_text, context)
        else:
            prompt, model, _ = compose_request.support_email(email_text)
        result = self._gemini.call(prompt, model)
        can_answer = result.get("can_answer", False)
        logger.info("Drafted support response for %s (uid=%s, can_answer=%s)", email.from_addr, email.uid, can_answer)
        return SupportDraft(email=email, can_answer=can_answer, draft_reply=result.get("reply", ""))

    def save_outbound(self, uid: str, draft: SupportDraft) -> None:
        """Save sent reply to thread history."""
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

    def discard(self, uid: str, draft: SupportDraft | None = None) -> None:
        """Clean up thread tracking for a skipped email."""
        thread_id = self._uid_thread.pop(uid, None)
        if draft and thread_id:
            em = draft.email
            rejected = IncomingEmail(
                uid="",
                from_addr=em.to_addr,
                to_addr=em.reply_to or em.from_addr,
                subject=em.subject,
                body=draft.draft_reply,
                date="",
                message_id=f"<draft-rejected-{uuid.uuid4().hex}>",
                in_reply_to=em.message_id,
            )
            self._db.save_message(thread_id, rejected, "draft_rejected")

    def _fetch_user_data(self, email_text: str, fallback_email: str) -> str:
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

    def _fetch_code_context(self, email_text: str) -> str:
        try:
            prompt, model, _ = compose_request.tech_search_terms(email_text)
            result = self._gemini.call(prompt, model)
            if not result.get("needs_code"):
                return ""
            terms = result.get("search_terms", [])
            if not terms:
                return ""

            seen_files: dict[str, tuple[str, int]] = {}
            for term in terms:
                for rel_path, lineno, _ in self._repo_gw.search_code(term):
                    if rel_path not in seen_files:
                        seen_files[rel_path] = (rel_path.split("/", 1)[0], lineno)

            if not seen_files:
                return ""

            snippets = []
            for rel_path, (repo, lineno) in list(seen_files.items())[:5]:
                filepath = rel_path.split("/", 1)[1] if "/" in rel_path else rel_path
                content = self._repo_gw.read_file(repo, filepath)
                if not content:
                    continue
                lines = content.splitlines()
                start = max(0, lineno - 25)
                end = min(len(lines), lineno + 25)
                snippet = "\n".join(lines[start:end])
                snippets.append(f"### {rel_path} (lines {start + 1}-{end})\n```\n{snippet}\n```")

            if not snippets:
                return ""
            logger.info("Code context: %d snippets from %d file matches", len(snippets), len(seen_files))
            return "## Контекст из кода\n\n" + "\n\n".join(snippets)
        except Exception as e:
            logger.error("Code context fetch failed: %s", e)
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
