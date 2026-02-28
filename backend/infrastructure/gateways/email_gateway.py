"""Email gateway — Gmail API for support inbox."""

from __future__ import annotations

import base64
import email
import logging
import time
from email.header import decode_header
from email.mime.text import MIMEText
from email.utils import parseaddr

from googleapiclient.discovery import build

from common.config import EMAIL_ADDRESS, get_gmail_creds
from common.models import IncomingEmail

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 30  # seconds between polls in idle_wait


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
        gmail = self._gmail()
        resp = gmail.users().messages().list(userId="me", q="is:unread").execute()
        message_ids = [m["id"] for m in resp.get("messages", [])]

        emails = []
        for msg_id in message_ids:
            raw_resp = gmail.users().messages().get(
                userId="me", id=msg_id, format="raw"
            ).execute()
            raw_bytes = base64.urlsafe_b64decode(raw_resp["raw"])
            msg = email.message_from_bytes(raw_bytes)
            emails.append(self._parse(msg_id, msg))
        return emails

    def mark_read(self, uid: str) -> None:
        """Remove UNREAD label from a message."""
        self._gmail().users().messages().modify(
            userId="me", id=uid, body={"removeLabelIds": ["UNREAD"]}
        ).execute()

    def send_reply(
        self, to: str, subject: str, body: str, in_reply_to: str = "", from_addr: str = ""
    ) -> None:
        """Send an email reply via Gmail API."""
        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = from_addr or EMAIL_ADDRESS
        msg["To"] = to
        msg["Subject"] = f"Re: {subject}" if not subject.startswith("Re:") else subject
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        self._gmail().users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()
        logger.info("Sent reply to %s: %s", to, subject)

    def idle_wait(self, timeout: int = 300) -> bool:
        """Poll for new unread mail. Returns True if unread count increases."""
        gmail = self._gmail()
        baseline = self._unread_count(gmail)
        elapsed = 0
        while elapsed < timeout:
            time.sleep(_POLL_INTERVAL)
            elapsed += _POLL_INTERVAL
            if self._unread_count(gmail) > baseline:
                return True
        return False

    @staticmethod
    def _unread_count(gmail) -> int:
        resp = gmail.users().messages().list(userId="me", q="is:unread").execute()
        return resp.get("resultSizeEstimate", 0)

    @staticmethod
    def _parse(uid: str, msg: email.message.Message) -> IncomingEmail:
        """Parse a raw email message into IncomingEmail."""
        subject_raw = msg.get("Subject", "")
        decoded_parts = decode_header(subject_raw)
        subject = ""
        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                subject += part.decode(charset or "utf-8", errors="replace")
            else:
                subject += part

        _, from_addr = parseaddr(msg.get("From", ""))
        _, to_addr = parseaddr(msg.get("To", ""))

        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        body = payload.decode(charset, errors="replace")
                        break
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                body = payload.decode(charset, errors="replace")

        return IncomingEmail(
            uid=uid,
            from_addr=from_addr,
            to_addr=to_addr,
            subject=subject,
            body=body.strip(),
            date=msg.get("Date", ""),
            message_id=msg.get("Message-ID", ""),
        )
