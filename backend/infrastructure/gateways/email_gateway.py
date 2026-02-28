"""Email gateway — IMAP read + SMTP send for support inbox."""

from __future__ import annotations

import email
import imaplib
import logging
import smtplib
from email.header import decode_header
from email.mime.text import MIMEText
from email.utils import parseaddr

from common.config import EMAIL_ADDRESS, EMAIL_IMAP_HOST, EMAIL_PASSWORD, EMAIL_SMTP_HOST
from common.models import IncomingEmail

logger = logging.getLogger(__name__)


class EmailGateway:
    """Wraps IMAP and SMTP for the support inbox."""

    def fetch_unread(self) -> list[IncomingEmail]:
        """Fetch all unread emails from the inbox."""
        with self._imap() as conn:
            conn.select("INBOX")
            _, data = conn.search(None, "UNSEEN")
            uids = data[0].split()
            emails = []
            for uid in uids:
                _, msg_data = conn.fetch(uid, "(RFC822)")
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)
                emails.append(self._parse(uid.decode(), msg))
            return emails

    def mark_read(self, uid: str) -> None:
        """Mark an email as seen."""
        with self._imap() as conn:
            conn.select("INBOX")
            conn.store(uid.encode(), "+FLAGS", "\\Seen")

    def send_reply(self, to: str, subject: str, body: str, in_reply_to: str = "", from_addr: str = "") -> None:
        """Send an email reply via SMTP. Threads correctly if in_reply_to is set."""
        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = from_addr or EMAIL_ADDRESS
        msg["To"] = to
        msg["Subject"] = f"Re: {subject}" if not subject.startswith("Re:") else subject
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to

        with smtplib.SMTP(EMAIL_SMTP_HOST, 587) as smtp:
            smtp.starttls()
            smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp.send_message(msg)
        logger.info("Sent reply to %s: %s", to, subject)

    def idle_wait(self, timeout: int = 300) -> bool:
        """IMAP IDLE — block until new mail or timeout. Returns True if new mail."""
        with self._imap() as conn:
            conn.select("INBOX")
            tag = conn._new_tag().decode()
            conn.send(f"{tag} IDLE\r\n".encode())
            conn.readline()  # + idling
            import select
            readable, _, _ = select.select([conn.socket()], [], [], timeout)
            conn.send(b"DONE\r\n")
            conn.readline()  # tagged response
            return bool(readable)

    def _imap(self) -> imaplib.IMAP4_SSL:
        conn = imaplib.IMAP4_SSL(EMAIL_IMAP_HOST)
        conn.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        return conn

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
