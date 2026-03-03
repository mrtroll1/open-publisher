"""Tests for backend/infrastructure/gateways/email_gateway.py — send_reply() only.

_parse() tests live in test_email_parse.py; no duplication here.
"""

import base64
import email
from unittest.mock import MagicMock, patch

import pytest


# ===================================================================
#  send_reply() — subject prefix logic + headers
# ===================================================================

class TestSendReply:

    def _make_gw(self):
        from backend.infrastructure.gateways.email_gateway import EmailGateway
        gw = EmailGateway()
        gw._service = MagicMock()
        return gw

    def _setup_mock_chain(self, gw):
        """Set up the Gmail API mock chain so send().execute() works."""
        mock_send = MagicMock()
        mock_send.execute.return_value = {"id": "sent_123"}
        gw._service.users.return_value.messages.return_value.send.return_value = mock_send
        return gw

    @patch("backend.infrastructure.gateways.email_gateway.EMAIL_ADDRESS", "support@republic.io")
    def test_adds_re_prefix(self):
        gw = self._make_gw()
        gw = self._setup_mock_chain(gw)
        gw.send_reply("user@example.com", "Hello", "Reply body")

        send_mock = gw._service.users().messages().send
        send_mock.assert_called_once()
        raw_b64 = send_mock.call_args[1]["body"]["raw"]
        msg = email.message_from_bytes(base64.urlsafe_b64decode(raw_b64))
        assert msg["Subject"] == "Re: Hello"

    @patch("backend.infrastructure.gateways.email_gateway.EMAIL_ADDRESS", "support@republic.io")
    def test_already_re_prefix(self):
        gw = self._make_gw()
        gw = self._setup_mock_chain(gw)
        gw.send_reply("user@example.com", "Re: Hello", "Reply body")

        raw_b64 = gw._service.users().messages().send.call_args[1]["body"]["raw"]
        msg = email.message_from_bytes(base64.urlsafe_b64decode(raw_b64))
        assert msg["Subject"] == "Re: Hello"

    @patch("backend.infrastructure.gateways.email_gateway.EMAIL_ADDRESS", "support@republic.io")
    def test_fwd_prefix_kept(self):
        gw = self._make_gw()
        gw = self._setup_mock_chain(gw)
        gw.send_reply("user@example.com", "Fwd: Report", "Body")

        raw_b64 = gw._service.users().messages().send.call_args[1]["body"]["raw"]
        msg = email.message_from_bytes(base64.urlsafe_b64decode(raw_b64))
        assert msg["Subject"] == "Fwd: Report"

    @patch("backend.infrastructure.gateways.email_gateway.EMAIL_ADDRESS", "support@republic.io")
    def test_fw_prefix_kept(self):
        gw = self._make_gw()
        gw = self._setup_mock_chain(gw)
        gw.send_reply("user@example.com", "Fw: Report", "Body")

        raw_b64 = gw._service.users().messages().send.call_args[1]["body"]["raw"]
        msg = email.message_from_bytes(base64.urlsafe_b64decode(raw_b64))
        assert msg["Subject"] == "Fw: Report"

    @patch("backend.infrastructure.gateways.email_gateway.EMAIL_ADDRESS", "support@republic.io")
    def test_in_reply_to_header(self):
        gw = self._make_gw()
        gw = self._setup_mock_chain(gw)
        gw.send_reply("user@example.com", "Hello", "Body", in_reply_to="<abc@mail.com>")

        raw_b64 = gw._service.users().messages().send.call_args[1]["body"]["raw"]
        msg = email.message_from_bytes(base64.urlsafe_b64decode(raw_b64))
        assert msg["In-Reply-To"] == "<abc@mail.com>"
        assert msg["References"] == "<abc@mail.com>"

    @patch("backend.infrastructure.gateways.email_gateway.EMAIL_ADDRESS", "support@republic.io")
    def test_no_in_reply_to_when_empty(self):
        gw = self._make_gw()
        gw = self._setup_mock_chain(gw)
        gw.send_reply("user@example.com", "Hello", "Body")

        raw_b64 = gw._service.users().messages().send.call_args[1]["body"]["raw"]
        msg = email.message_from_bytes(base64.urlsafe_b64decode(raw_b64))
        assert msg["In-Reply-To"] is None
        assert msg["References"] is None

    @patch("backend.infrastructure.gateways.email_gateway.EMAIL_ADDRESS", "support@republic.io")
    def test_custom_from_addr(self):
        gw = self._make_gw()
        gw = self._setup_mock_chain(gw)
        gw.send_reply("user@example.com", "Hi", "Body", from_addr="custom@republic.io")

        raw_b64 = gw._service.users().messages().send.call_args[1]["body"]["raw"]
        msg = email.message_from_bytes(base64.urlsafe_b64decode(raw_b64))
        assert msg["From"] == "custom@republic.io"

    @patch("backend.infrastructure.gateways.email_gateway.EMAIL_ADDRESS", "support@republic.io")
    def test_default_from_addr(self):
        gw = self._make_gw()
        gw = self._setup_mock_chain(gw)
        gw.send_reply("user@example.com", "Hi", "Body")

        raw_b64 = gw._service.users().messages().send.call_args[1]["body"]["raw"]
        msg = email.message_from_bytes(base64.urlsafe_b64decode(raw_b64))
        assert msg["From"] == "support@republic.io"

    @patch("backend.infrastructure.gateways.email_gateway.EMAIL_ADDRESS", "support@republic.io")
    def test_to_address_set(self):
        gw = self._make_gw()
        gw = self._setup_mock_chain(gw)
        gw.send_reply("recipient@example.com", "Hi", "Body")

        raw_b64 = gw._service.users().messages().send.call_args[1]["body"]["raw"]
        msg = email.message_from_bytes(base64.urlsafe_b64decode(raw_b64))
        assert msg["To"] == "recipient@example.com"
