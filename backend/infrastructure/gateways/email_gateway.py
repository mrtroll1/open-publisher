"""Email gateway — Gmail API for support inbox."""

from __future__ import annotations

import base64
import email
import logging
import time
from email.mime.text import MIMEText

from googleapiclient.discovery import build

from common.email_utils import parse_email_message
from common.config import EMAIL_ADDRESS, get_gmail_creds
from common.models import IncomingEmail

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 60  # seconds between polls
_RECENT_WINDOW = 120  # fetch emails no older than this (seconds), 2x poll for overlap safety


class EmailGateway:
    """Wraps Gmail API for the support inbox."""

    def __init__(self):
        self._service = None

    def _gmail(self):
        if self._service is None:
            creds = get_gmail_creds()
            self._service = build("gmail", "v1", credentials=creds)
        return self._service

    def fetch_unread(self) -> list[IncomingEmail]:
        """Fetch all unread emails from the inbox."""
        try:
            gmail = self._gmail()
            after = int(time.time()) - _RECENT_WINDOW
            resp = gmail.users().messages().list(
                userId="me", q=f"is:unread after:{after}"
            ).execute()
            message_ids = [m["id"] for m in resp.get("messages", [])]
            logger.info("Gmail poll: %d recent unread messages", len(message_ids))

            emails = []
            for msg_id in message_ids:
                raw_resp = gmail.users().messages().get(
                    userId="me", id=msg_id, format="raw"
                ).execute()
                raw_bytes = base64.urlsafe_b64decode(raw_resp["raw"])
                msg = email.message_from_bytes(raw_bytes)
                emails.append(parse_email_message(msg_id, msg))
            return emails
        except Exception:
            logger.warning("Failed to fetch unread emails", exc_info=True)
            return []

    def mark_read(self, uid: str) -> None:
        """Remove UNREAD label from a message."""
        try:
            self._gmail().users().messages().modify(
                userId="me", id=uid, body={"removeLabelIds": ["UNREAD"]}
            ).execute()
        except Exception:
            logger.warning("Failed to mark message %s as read", uid, exc_info=True)

    def send_reply(
        self, to: str, subject: str, body: str, in_reply_to: str = "", from_addr: str = ""
    ) -> None:
        """Send an email reply via Gmail API."""
        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = from_addr or EMAIL_ADDRESS
        msg["To"] = to
        if subject.startswith("Re:") or subject.startswith("Fwd:") or subject.startswith("Fw:"):
            msg["Subject"] = subject
        else:
            msg["Subject"] = f"Re: {subject}"
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        try:
            self._gmail().users().messages().send(
                userId="me", body={"raw": raw}
            ).execute()
            logger.info("Sent reply to %s: %s", to, subject)
        except Exception:
            logger.error("Failed to send reply to %s: %s", to, subject, exc_info=True)
            raise

    def idle_wait(self, timeout: int = 300) -> bool:
        """Poll for new unread mail. Just sleeps — actual check happens in fetch_unread."""
        time.sleep(min(timeout, _POLL_INTERVAL))
        return True

    _parse = staticmethod(parse_email_message)
