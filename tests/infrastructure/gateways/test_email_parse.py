"""Tests for parse_email_message() — pure email parsing, no network."""

import email
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pytest

from common.email_utils import parse_email_message
# Backward compat: _parse is still accessible
from backend.infrastructure.gateways.email_gateway import EmailGateway


def _make_simple_email(
    *,
    subject="Test Subject",
    from_addr="sender@example.com",
    to_addr="support@example.com",
    body="Hello, this is the body.",
    reply_to="",
    message_id="<msg001@example.com>",
    in_reply_to="",
    references="",
    date_str="Mon, 01 Jan 2026 12:00:00 +0000",
) -> email.message.Message:
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = f"Sender Name <{from_addr}>"
    msg["To"] = f"Support <{to_addr}>"
    msg["Date"] = date_str
    msg["Message-ID"] = message_id
    if reply_to:
        msg["Reply-To"] = reply_to
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    return msg


def _make_multipart_email(
    plain_body="Plain text body",
    html_body="<p>HTML body</p>",
    **kwargs,
) -> email.message.Message:
    msg = MIMEMultipart("alternative")
    msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    msg["Subject"] = kwargs.get("subject", "Test Subject")
    msg["From"] = f"Sender <{kwargs.get('from_addr', 'sender@example.com')}>"
    msg["To"] = f"Support <{kwargs.get('to_addr', 'support@example.com')}>"
    msg["Date"] = kwargs.get("date_str", "Mon, 01 Jan 2026 12:00:00 +0000")
    msg["Message-ID"] = kwargs.get("message_id", "<msg001@example.com>")
    return msg


# ===================================================================
#  Basic parsing
# ===================================================================

class TestParseBasic:

    def test_uid_preserved(self):
        msg = _make_simple_email()
        result = parse_email_message("uid-123", msg)
        assert result.uid == "uid-123"

    def test_from_addr_extracted(self):
        msg = _make_simple_email(from_addr="test@domain.org")
        result = parse_email_message("1", msg)
        assert result.from_addr == "test@domain.org"

    def test_to_addr_extracted(self):
        msg = _make_simple_email(to_addr="inbox@corp.com")
        result = parse_email_message("1", msg)
        assert result.to_addr == "inbox@corp.com"

    def test_subject_extracted(self):
        msg = _make_simple_email(subject="Important Topic")
        result = parse_email_message("1", msg)
        assert result.subject == "Important Topic"

    def test_body_extracted(self):
        msg = _make_simple_email(body="The body text.")
        result = parse_email_message("1", msg)
        assert result.body == "The body text."

    def test_body_stripped(self):
        msg = _make_simple_email(body="  trimmed  \n\n")
        result = parse_email_message("1", msg)
        assert result.body == "trimmed"

    def test_date_extracted(self):
        msg = _make_simple_email(date_str="Tue, 15 Feb 2026 10:30:00 +0300")
        result = parse_email_message("1", msg)
        assert result.date == "Tue, 15 Feb 2026 10:30:00 +0300"

    def test_message_id_extracted(self):
        msg = _make_simple_email(message_id="<unique-id@mail.com>")
        result = parse_email_message("1", msg)
        assert result.message_id == "<unique-id@mail.com>"


# ===================================================================
#  Reply-To and threading headers
# ===================================================================

class TestParseThreading:

    def test_reply_to_extracted(self):
        msg = _make_simple_email(reply_to="replies@example.com")
        result = parse_email_message("1", msg)
        assert result.reply_to == "replies@example.com"

    def test_reply_to_empty_when_absent(self):
        msg = _make_simple_email()
        result = parse_email_message("1", msg)
        assert result.reply_to == ""

    def test_in_reply_to_extracted(self):
        msg = _make_simple_email(in_reply_to="<parent@example.com>")
        result = parse_email_message("1", msg)
        assert result.in_reply_to == "<parent@example.com>"

    def test_references_extracted(self):
        msg = _make_simple_email(references="<ref1@a.com> <ref2@a.com>")
        result = parse_email_message("1", msg)
        assert result.references == "<ref1@a.com> <ref2@a.com>"


# ===================================================================
#  Multipart emails
# ===================================================================

class TestParseMultipart:

    def test_extracts_plain_text_from_multipart(self):
        msg = _make_multipart_email(plain_body="Plain version")
        result = parse_email_message("1", msg)
        assert result.body == "Plain version"

    def test_ignores_html_part(self):
        msg = _make_multipart_email(
            plain_body="Only plain",
            html_body="<b>Not this</b>",
        )
        result = parse_email_message("1", msg)
        assert "<b>" not in result.body
        assert result.body == "Only plain"


# ===================================================================
#  Encoded subjects
# ===================================================================

class TestParseEncodedSubject:

    def test_utf8_encoded_subject(self):
        raw_subject = "=?utf-8?B?0KLQtdGB0YLQvtCy0LDRjyDRgtC10LzQsA==?="
        msg = _make_simple_email()
        msg.replace_header("Subject", raw_subject)
        result = parse_email_message("1", msg)
        assert result.subject == "Тестовая тема"

    def test_plain_ascii_subject(self):
        msg = _make_simple_email(subject="Simple Subject")
        result = parse_email_message("1", msg)
        assert result.subject == "Simple Subject"


# ===================================================================
#  Edge cases
# ===================================================================

class TestParseEdgeCases:

    def test_missing_headers_default_to_empty(self):
        msg = email.message.Message()
        msg.set_payload("bare body")
        result = parse_email_message("1", msg)
        assert result.from_addr == ""
        assert result.to_addr == ""
        assert result.subject == ""
        assert result.date == ""
        assert result.message_id == ""

    def test_empty_body(self):
        msg = MIMEText("", "plain", "utf-8")
        msg["Subject"] = "Empty"
        msg["From"] = "a@b.c"
        msg["To"] = "d@e.f"
        msg["Date"] = "Mon, 01 Jan 2026 00:00:00 +0000"
        result = parse_email_message("1", msg)
        assert result.body == ""
