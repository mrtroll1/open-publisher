"""Tests for backend/domain/tech_support_handler.py"""

from unittest.mock import patch

from backend.commands.support_handler import TechSupportHandler
from common.models import IncomingEmail, SupportDraft


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
#  Helpers
# ===================================================================

def _make_email(**overrides) -> IncomingEmail:
    defaults = dict(
        uid="u1", from_addr="user@test.com", to_addr="support@test.com",
        subject="Help", body="I need help", date="2026-01-15",
        message_id="<msg-1>", in_reply_to="",
    )
    defaults.update(overrides)
    return IncomingEmail(**defaults)


@patch("backend.commands.support_handler.DbGateway")
@patch("backend.commands.support_handler.RepoGateway")
@patch("backend.commands.support_handler.SupportUserLookup")
@patch("backend.commands.support_handler.GeminiGateway")
def _make_handler(MockGemini, MockLookup, MockRepo, MockDb):
    handler = TechSupportHandler()
    return handler, handler._db, handler._gemini, handler._user_lookup


# ===================================================================
#  draft_reply() — full flow
# ===================================================================

class TestDraftReply:

    def test_full_flow_returns_support_draft(self):
        handler, mock_db, mock_gemini, mock_lookup = _make_handler()
        email = _make_email()
        mock_db.find_thread.return_value = "thread-1"
        mock_db.get_thread_history.return_value = [{"direction": "inbound", "from_addr": "user@test.com", "date": "2026-01-15", "subject": "Help", "body": "I need help"}]
        # triage call, then draft call
        mock_gemini.call.side_effect = [
            {"needs": ["account_info"], "lookup_email": "user@test.com"},  # triage
            {"can_answer": True, "reply": "Here is the answer"},  # draft
        ]
        mock_lookup.fetch_and_format.return_value = "## Account info"

        result = handler.draft_reply(email)

        assert isinstance(result, SupportDraft)
        assert result.email is email
        assert result.can_answer is True
        assert result.draft_reply == "Here is the answer"
        mock_db.find_thread.assert_called_once_with("<msg-1>", "", "Help")
        mock_db.save_message.assert_called_once_with("thread-1", email, "inbound")
        mock_lookup.fetch_and_format.assert_called_once_with("user@test.com", ["account_info"])

    def test_includes_thread_history_when_multiple_messages(self):
        handler, mock_db, mock_gemini, mock_lookup = _make_handler()
        email = _make_email(uid="u2")
        mock_db.find_thread.return_value = "thread-2"
        mock_db.get_thread_history.return_value = [
            {"direction": "inbound", "from_addr": "user@test.com", "date": "2026-01-14", "subject": "Help", "body": "First msg"},
            {"direction": "outbound", "from_addr": "support@test.com", "date": "2026-01-14", "subject": "Re: Help", "body": "Reply"},
            {"direction": "inbound", "from_addr": "user@test.com", "date": "2026-01-15", "subject": "Re: Help", "body": "Follow-up"},
        ]
        mock_gemini.call.side_effect = [
            {"needs": [], "lookup_email": ""},  # triage — no needs
            {"can_answer": True, "reply": "Got it"},  # draft
        ]

        result = handler.draft_reply(email)

        # With history > 1, support_email should be called with context
        # The second gemini.call gets the prompt with context
        assert mock_gemini.call.call_count == 2
        assert result.draft_reply == "Got it"

    def test_returns_can_answer_false(self):
        handler, mock_db, mock_gemini, _ = _make_handler()
        email = _make_email()
        mock_db.find_thread.return_value = "t1"
        mock_db.get_thread_history.return_value = []
        mock_gemini.call.side_effect = [
            {"needs": [], "lookup_email": ""},
            {"can_answer": False, "reply": "I cannot help with this"},
        ]

        result = handler.draft_reply(email)

        assert result.can_answer is False
        assert result.draft_reply == "I cannot help with this"


# ===================================================================
#  save_outbound() — saves outbound message to DB
# ===================================================================

class TestSaveOutbound:

    def test_saves_outbound_message_with_correct_fields(self):
        handler, mock_db, _, _ = _make_handler()
        email = _make_email(uid="u-out", to_addr="support@test.com",
                            from_addr="user@test.com", subject="Help")
        draft = SupportDraft(email=email, can_answer=True, draft_reply="The answer")
        handler._uid_thread["u-out"] = "thread-out"

        handler.save_outbound("u-out", draft)

        mock_db.save_message.assert_called_once()
        call_args = mock_db.save_message.call_args
        assert call_args[0][0] == "thread-out"
        outbound_email = call_args[0][1]
        assert outbound_email.from_addr == "support@test.com"  # swapped: to_addr of original
        assert outbound_email.to_addr == "user@test.com"  # swapped: from_addr of original
        assert outbound_email.body == "The answer"
        assert outbound_email.subject == "Help"
        assert call_args[0][2] == "outbound"
        # uid removed from tracking
        assert "u-out" not in handler._uid_thread

    def test_no_op_when_uid_not_tracked(self):
        handler, mock_db, _, _ = _make_handler()
        email = _make_email()
        draft = SupportDraft(email=email, can_answer=True, draft_reply="X")

        handler.save_outbound("unknown-uid", draft)

        mock_db.save_message.assert_not_called()


# ===================================================================
#  discard() — cleanup + optional rejected draft save
# ===================================================================

class TestDiscard:

    def test_saves_rejected_draft_when_draft_provided(self):
        handler, mock_db, _, _ = _make_handler()
        email = _make_email(uid="u-disc")
        draft = SupportDraft(email=email, can_answer=True, draft_reply="Rejected reply")
        handler._uid_thread["u-disc"] = "thread-disc"

        handler.discard("u-disc", draft=draft)

        mock_db.save_message.assert_called_once()
        call_args = mock_db.save_message.call_args
        assert call_args[0][0] == "thread-disc"
        rejected_email = call_args[0][1]
        assert rejected_email.body == "Rejected reply"
        assert call_args[0][2] == "draft_rejected"
        assert "u-disc" not in handler._uid_thread

    def test_just_cleans_up_when_no_draft(self):
        handler, mock_db, _, _ = _make_handler()
        handler._uid_thread["u-clean"] = "thread-clean"

        handler.discard("u-clean", draft=None)

        mock_db.save_message.assert_not_called()
        assert "u-clean" not in handler._uid_thread

    def test_no_op_when_uid_not_tracked_and_no_draft(self):
        handler, mock_db, _, _ = _make_handler()

        handler.discard("nonexistent")

        mock_db.save_message.assert_not_called()


# ===================================================================
#  _fetch_user_data() — triage LLM + user lookup
# ===================================================================

class TestFetchUserData:

    def test_calls_llm_triage_then_fetches_user_data(self):
        handler, _, mock_gemini, mock_lookup = _make_handler()
        mock_gemini.call.return_value = {
            "needs": ["subscription_info", "payments_info"],
            "lookup_email": "found@test.com",
        }
        mock_lookup.fetch_and_format.return_value = "## User data here"

        result = handler._fetch_user_data("email text", "fallback@test.com")

        assert result == "## User data here"
        mock_gemini.call.assert_called_once()
        mock_lookup.fetch_and_format.assert_called_once_with(
            "found@test.com", ["subscription_info", "payments_info"],
        )

    def test_uses_fallback_email_when_llm_returns_none(self):
        handler, _, mock_gemini, mock_lookup = _make_handler()
        mock_gemini.call.return_value = {
            "needs": ["account_info"],
            "lookup_email": None,
        }
        mock_lookup.fetch_and_format.return_value = "data"

        handler._fetch_user_data("email text", "fallback@test.com")

        mock_lookup.fetch_and_format.assert_called_once_with("fallback@test.com", ["account_info"])

    def test_returns_empty_when_no_needs(self):
        handler, _, mock_gemini, mock_lookup = _make_handler()
        mock_gemini.call.return_value = {"needs": [], "lookup_email": "x@y.com"}

        result = handler._fetch_user_data("email text", "fallback@test.com")

        assert result == ""
        mock_lookup.fetch_and_format.assert_not_called()

    def test_returns_empty_on_exception(self):
        handler, _, mock_gemini, mock_lookup = _make_handler()
        mock_gemini.call.side_effect = RuntimeError("LLM down")

        result = handler._fetch_user_data("email text", "fallback@test.com")

        assert result == ""
