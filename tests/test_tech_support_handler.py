"""Tests for backend/domain/tech_support_handler.py"""

import pytest
from unittest.mock import MagicMock, patch

from backend.domain.tech_support_handler import TechSupportHandler
from common.models import IncomingEmail


# ===================================================================
#  _format_thread()
# ===================================================================

class TestFormatThread:

    def test_single_inbound_message(self):
        history = [{
            "direction": "inbound",
            "from_addr": "user@test.com",
            "date": "2026-01-15",
            "subject": "Help me",
            "body": "I need help.",
        }]
        result = TechSupportHandler._format_thread(history)
        assert "входящее" in result
        assert "user@test.com" in result
        assert "Help me" in result
        assert "I need help." in result

    def test_single_outbound_message(self):
        history = [{
            "direction": "outbound",
            "from_addr": "support@test.com",
            "date": "2026-01-15",
            "subject": "Re: Help me",
            "body": "Here is how to fix it.",
        }]
        result = TechSupportHandler._format_thread(history)
        assert "исходящее" in result
        assert "support@test.com" in result

    def test_multi_message_thread(self):
        history = [
            {
                "direction": "inbound",
                "from_addr": "user@test.com",
                "date": "2026-01-15 10:00",
                "subject": "Question",
                "body": "First message",
            },
            {
                "direction": "outbound",
                "from_addr": "support@test.com",
                "date": "2026-01-15 11:00",
                "subject": "Re: Question",
                "body": "Reply here",
            },
            {
                "direction": "inbound",
                "from_addr": "user@test.com",
                "date": "2026-01-15 12:00",
                "subject": "Re: Re: Question",
                "body": "Follow-up",
            },
        ]
        result = TechSupportHandler._format_thread(history)
        assert result.count("входящее") == 2
        assert result.count("исходящее") == 1
        assert "First message" in result
        assert "Reply here" in result
        assert "Follow-up" in result

    def test_header_present(self):
        result = TechSupportHandler._format_thread([])
        assert "## История переписки" in result

    def test_empty_history(self):
        result = TechSupportHandler._format_thread([])
        assert "## История переписки" in result
        # Should just be the header line
        lines = result.strip().split("\n")
        assert len(lines) == 1

    def test_empty_body(self):
        history = [{
            "direction": "inbound",
            "from_addr": "a@b.c",
            "date": "",
            "subject": "S",
            "body": "",
        }]
        result = TechSupportHandler._format_thread(history)
        assert "a@b.c" in result


# ===================================================================
#  draft_reply() — verify _fetch_code_context is NOT called
# ===================================================================

class TestDraftReplyNoCodeContext:

    @patch("backend.domain.tech_support_handler.DbGateway")
    @patch("backend.domain.tech_support_handler.RepoGateway")
    @patch("backend.domain.tech_support_handler.SupportUserLookup")
    @patch("backend.domain.tech_support_handler.GeminiGateway")
    def test_draft_reply_does_not_call_fetch_code_context(
        self, MockGemini, MockLookup, MockRepo, MockDb,
    ):
        mock_db = MockDb.return_value
        mock_db.find_thread.return_value = "thread-1"
        mock_db.get_thread_history.return_value = []

        mock_gemini = MockGemini.return_value
        mock_gemini.call.return_value = {"reply": "test reply", "can_answer": True}

        handler = TechSupportHandler()

        email = IncomingEmail(
            uid="u1", from_addr="user@test.com", subject="Help",
            body="I have a question", date="2026-01-01",
        )

        with patch.object(handler, "_fetch_code_context") as mock_code_ctx:
            handler.draft_reply(email)
            mock_code_ctx.assert_not_called()
