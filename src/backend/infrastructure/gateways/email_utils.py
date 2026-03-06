"""Email parsing utilities — pure functions, no API dependencies."""

from __future__ import annotations

import email
from email.header import decode_header
from email.utils import parseaddr

from backend.models import IncomingEmail


def parse_email_message(uid: str, msg: email.message.Message) -> IncomingEmail:
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
    _, reply_to = parseaddr(msg.get("Reply-To", ""))

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
        reply_to=reply_to,
        subject=subject,
        body=body.strip(),
        date=msg.get("Date", ""),
        message_id=msg.get("Message-ID", ""),
        in_reply_to=msg.get("In-Reply-To", "").strip(),
        references=msg.get("References", "").strip(),
    )
