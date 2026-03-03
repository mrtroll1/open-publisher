"""Tests for backend/domain/services/admin_service.py."""

from unittest.mock import MagicMock, call

from backend.domain.services.admin_service import (
    _GREETING_PREFIXES,
    classify_draft_reply,
    store_admin_feedback,
)


# ===================================================================
#  classify_draft_reply — pure logic
# ===================================================================

class TestClassifyDraftReply:

    def test_greeting_returns_replacement(self):
        assert classify_draft_reply("Здравствуйте, вот ваш ответ") == "replacement"

    def test_greeting_case_insensitive(self):
        assert classify_draft_reply("ДОБРЫЙ ДЕНЬ, коллеги") == "replacement"

    def test_greeting_with_leading_whitespace(self):
        assert classify_draft_reply("  Hello, this is a reply") == "replacement"

    def test_non_greeting_returns_feedback(self):
        assert classify_draft_reply("Не отвечай на такие письма") == "feedback"

    def test_empty_string_returns_feedback(self):
        assert classify_draft_reply("") == "feedback"

    def test_all_greeting_prefixes_recognized(self):
        for prefix in _GREETING_PREFIXES:
            text = f"{prefix} some continuation text"
            assert classify_draft_reply(text) == "replacement", (
                f"Prefix '{prefix}' was not recognized as a greeting"
            )

    def test_greeting_in_middle_returns_feedback(self):
        assert classify_draft_reply("Please say Здравствуйте to them") == "feedback"

    def test_dear_prefix(self):
        assert classify_draft_reply("Dear colleague, ...") == "replacement"

    def test_hi_with_comma(self):
        assert classify_draft_reply("Hi, how are you?") == "replacement"

    def test_hi_with_space(self):
        assert classify_draft_reply("Hi there") == "replacement"


# ===================================================================
#  store_admin_feedback — mock retriever
# ===================================================================

class TestStoreAdminFeedback:

    def test_calls_retriever_store_feedback(self):
        retriever = MagicMock()
        store_admin_feedback("Don't reply to spam", "tech_support", retriever)
        retriever.store_feedback.assert_called_once_with(
            "Don't reply to spam", domain="tech_support",
        )

    def test_swallows_exception(self):
        retriever = MagicMock()
        retriever.store_feedback.side_effect = RuntimeError("db error")

        # Should not raise
        store_admin_feedback("text", "some_domain", retriever)

    def test_passes_domain_through(self):
        retriever = MagicMock()
        store_admin_feedback("text", "custom_domain", retriever)
        retriever.store_feedback.assert_called_once_with("text", domain="custom_domain")
