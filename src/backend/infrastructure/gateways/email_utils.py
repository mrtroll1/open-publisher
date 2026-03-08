"""Email parsing utilities — pure functions, no API dependencies."""

from __future__ import annotations

import email
from email.header import decode_header
from email.utils import parseaddr

from backend.models import IncomingEmail


def _decode_subject(msg: email.message.Message) -> str:
    decoded_parts = decode_header(msg.get("Subject", ""))
    return "".join(
        part.decode(charset or "utf-8", errors="replace") if isinstance(part, bytes) else part
        for part, charset in decoded_parts
    )


def _addr(msg: email.message.Message, header: str) -> str:
    return parseaddr(msg.get(header, ""))[1]


def _decode_payload(part: email.message.Message) -> str:
    payload = part.get_payload(decode=True)
    if not payload:
        return ""
    charset = part.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def _extract_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                return _decode_payload(part)
        return ""
    return _decode_payload(msg)


def parse_email_message(uid: str, msg: email.message.Message) -> IncomingEmail:
    return IncomingEmail(
        uid=uid,
        from_addr=_addr(msg, "From"),
        to_addr=_addr(msg, "To"),
        reply_to=_addr(msg, "Reply-To"),
        subject=_decode_subject(msg),
        body=_extract_body(msg).strip(),
        date=msg.get("Date", ""),
        message_id=msg.get("Message-ID", ""),
        in_reply_to=msg.get("In-Reply-To", "").strip(),
        references=msg.get("References", "").strip(),
    )
