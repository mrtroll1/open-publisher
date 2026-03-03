import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from common.models import EditorialItem, IncomingEmail, SupportDraft
from telegram_bot import replies


# ---------------------------------------------------------------------------
#  Factories
# ---------------------------------------------------------------------------

def _email(**overrides) -> IncomingEmail:
    kwargs = dict(
        uid="email-1", from_addr="user@example.com", to_addr="support@test.com",
        reply_to="", subject="Help me", body="I have a problem", date="2025-01-01",
    )
    kwargs.update(overrides)
    return IncomingEmail(**kwargs)


def _draft(**overrides) -> SupportDraft:
    kwargs = dict(email=_email(), can_answer=True, draft_reply="Here is the answer")
    kwargs.update(overrides)
    return SupportDraft(**kwargs)


def _editorial(**overrides) -> EditorialItem:
    kwargs = dict(email=_email(uid="ed-1", subject="Story pitch"), reply_to_sender="")
    kwargs.update(overrides)
    return EditorialItem(**kwargs)


def _callback(data: str, chat_id: int = 100, message_id: int = 10) -> AsyncMock:
    cb = AsyncMock()
    cb.data = data
    cb.answer = AsyncMock()
    cb.message = AsyncMock()
    cb.message.chat.id = chat_id
    cb.message.message_id = message_id
    cb.message.edit_text = AsyncMock()
    cb.message.edit_reply_markup = AsyncMock()
    return cb


# ===================================================================
#  handle_support_callback
# ===================================================================

class TestHandleSupportCallback:

    @patch("telegram_bot.handlers.support_handlers._safe_edit_text", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.support_handlers._inbox")
    def test_send_action_approves(self, mock_inbox, mock_edit):
        from telegram_bot.handlers.support_handlers import handle_support_callback

        draft = _draft()
        mock_inbox.get_pending_support.return_value = draft
        mock_inbox.approve_support = MagicMock()

        cb = _callback("support:send:email-1")
        asyncio.run(handle_support_callback(cb))

        cb.answer.assert_awaited_once()
        mock_inbox.approve_support.assert_called_once_with("email-1")
        mock_edit.assert_awaited_once()
        assert "user@example.com" in mock_edit.call_args[0][1]

    @patch("telegram_bot.handlers.support_handlers._safe_edit_text", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.support_handlers._inbox")
    def test_send_action_uses_reply_to_when_set(self, mock_inbox, mock_edit):
        from telegram_bot.handlers.support_handlers import handle_support_callback

        draft = _draft(email=_email(reply_to="reply@example.com"))
        mock_inbox.get_pending_support.return_value = draft
        mock_inbox.approve_support = MagicMock()

        cb = _callback("support:send:email-1")
        asyncio.run(handle_support_callback(cb))

        text = mock_edit.call_args[0][1]
        assert "reply@example.com" in text

    @patch("telegram_bot.handlers.support_handlers._safe_edit_text", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.support_handlers._inbox")
    def test_skip_action_skips(self, mock_inbox, mock_edit):
        from telegram_bot.handlers.support_handlers import handle_support_callback

        draft = _draft()
        mock_inbox.get_pending_support.return_value = draft
        mock_inbox.skip_support = MagicMock()

        cb = _callback("support:skip:email-1")
        asyncio.run(handle_support_callback(cb))

        mock_inbox.skip_support.assert_called_once_with("email-1")
        text = mock_edit.call_args[0][1]
        assert "user@example.com" in text

    @patch("telegram_bot.handlers.support_handlers._safe_edit_text", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.support_handlers._inbox")
    def test_expired_draft(self, mock_inbox, mock_edit):
        from telegram_bot.handlers.support_handlers import handle_support_callback

        mock_inbox.get_pending_support.return_value = None

        cb = _callback("support:send:email-1")
        asyncio.run(handle_support_callback(cb))

        mock_edit.assert_awaited_once()
        assert mock_edit.call_args[0][1] == replies.tech_support.expired

    def test_invalid_callback_data_ignored(self):
        from telegram_bot.handlers.support_handlers import handle_support_callback

        cb = _callback("support:send")  # Only 2 parts
        asyncio.run(handle_support_callback(cb))
        cb.answer.assert_awaited_once()

    @patch("telegram_bot.handlers.support_handlers._safe_edit_text", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.support_handlers._inbox")
    def test_unknown_action_does_nothing(self, mock_inbox, mock_edit):
        from telegram_bot.handlers.support_handlers import handle_support_callback

        mock_inbox.get_pending_support.return_value = _draft()
        mock_inbox.approve_support = MagicMock()
        mock_inbox.skip_support = MagicMock()

        cb = _callback("support:unknown:email-1")
        asyncio.run(handle_support_callback(cb))

        mock_inbox.approve_support.assert_not_called()
        mock_inbox.skip_support.assert_not_called()


# ===================================================================
#  handle_editorial_callback
# ===================================================================

class TestHandleEditorialCallback:

    @patch("telegram_bot.handlers.support_handlers._safe_edit_text", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.support_handlers._inbox")
    def test_fwd_action_approves(self, mock_inbox, mock_edit):
        from telegram_bot.handlers.support_handlers import handle_editorial_callback

        item = _editorial()
        mock_inbox.get_pending_editorial.return_value = item
        mock_inbox.approve_editorial = MagicMock()

        cb = _callback("editorial:fwd:ed-1")
        asyncio.run(handle_editorial_callback(cb))

        cb.answer.assert_awaited_once()
        mock_inbox.approve_editorial.assert_called_once_with("ed-1")
        text = mock_edit.call_args[0][1]
        assert "user@example.com" in text

    @patch("telegram_bot.handlers.support_handlers._safe_edit_text", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.support_handlers._inbox")
    def test_skip_action_skips(self, mock_inbox, mock_edit):
        from telegram_bot.handlers.support_handlers import handle_editorial_callback

        item = _editorial()
        mock_inbox.get_pending_editorial.return_value = item
        mock_inbox.skip_editorial = MagicMock()

        cb = _callback("editorial:skip:ed-1")
        asyncio.run(handle_editorial_callback(cb))

        mock_inbox.skip_editorial.assert_called_once_with("ed-1")

    @patch("telegram_bot.handlers.support_handlers._safe_edit_text", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.support_handlers._inbox")
    def test_expired_editorial(self, mock_inbox, mock_edit):
        from telegram_bot.handlers.support_handlers import handle_editorial_callback

        mock_inbox.get_pending_editorial.return_value = None

        cb = _callback("editorial:fwd:ed-1")
        asyncio.run(handle_editorial_callback(cb))

        assert mock_edit.call_args[0][1] == replies.editorial.expired

    def test_invalid_callback_data(self):
        from telegram_bot.handlers.support_handlers import handle_editorial_callback

        cb = _callback("editorial:fwd")
        asyncio.run(handle_editorial_callback(cb))
        cb.answer.assert_awaited_once()


# ===================================================================
#  _send_support_draft
# ===================================================================

class TestSendSupportDraft:

    @patch("telegram_bot.handlers.support_handlers._support_draft_map", {})
    @patch("telegram_bot.handlers.support_handlers.bot", new_callable=AsyncMock)
    def test_sends_message_with_buttons(self, mock_bot):
        from telegram_bot.handlers.support_handlers import _send_support_draft, _support_draft_map

        draft = _draft()
        sent_msg = MagicMock()
        sent_msg.message_id = 42
        mock_bot.send_message.return_value = sent_msg

        asyncio.run(_send_support_draft(100, draft))

        mock_bot.send_message.assert_awaited_once()
        call_kwargs = mock_bot.send_message.call_args
        assert call_kwargs[0][0] == 100
        text = call_kwargs[0][1]
        assert "user@example.com" in text
        assert "Help me" in text
        assert replies.tech_support.draft_header in text
        assert "Here is the answer" in text
        # Verify reply_markup has send/skip buttons
        markup = call_kwargs[1]["reply_markup"]
        buttons = markup.inline_keyboard[0]
        assert len(buttons) == 2

    @patch("telegram_bot.handlers.support_handlers._support_draft_map", {})
    @patch("telegram_bot.handlers.support_handlers.bot", new_callable=AsyncMock)
    def test_populates_support_draft_map(self, mock_bot):
        from telegram_bot.handlers.support_handlers import _send_support_draft, _support_draft_map

        draft = _draft()
        sent_msg = MagicMock()
        sent_msg.message_id = 42
        mock_bot.send_message.return_value = sent_msg

        asyncio.run(_send_support_draft(100, draft))

        assert _support_draft_map[(100, 42)] == "email-1"

    @patch("telegram_bot.handlers.support_handlers._support_draft_map", {})
    @patch("telegram_bot.handlers.support_handlers.bot", new_callable=AsyncMock)
    def test_uncertain_draft_uses_uncertain_header(self, mock_bot):
        from telegram_bot.handlers.support_handlers import _send_support_draft

        draft = _draft(can_answer=False)
        sent_msg = MagicMock()
        sent_msg.message_id = 42
        mock_bot.send_message.return_value = sent_msg

        asyncio.run(_send_support_draft(100, draft))

        text = mock_bot.send_message.call_args[0][1]
        assert replies.tech_support.draft_header_uncertain in text

    @patch("telegram_bot.handlers.support_handlers._support_draft_map", {})
    @patch("telegram_bot.handlers.support_handlers.bot", new_callable=AsyncMock)
    def test_reply_to_different_from_from_addr_shows_both(self, mock_bot):
        from telegram_bot.handlers.support_handlers import _send_support_draft

        draft = _draft(email=_email(reply_to="other@example.com"))
        sent_msg = MagicMock()
        sent_msg.message_id = 42
        mock_bot.send_message.return_value = sent_msg

        asyncio.run(_send_support_draft(100, draft))

        text = mock_bot.send_message.call_args[0][1]
        assert "Reply-To: other@example.com" in text
        assert "From: user@example.com" in text

    @patch("telegram_bot.handlers.support_handlers._support_draft_map", {})
    @patch("telegram_bot.handlers.support_handlers.bot", new_callable=AsyncMock)
    def test_reply_to_same_as_from_not_shown(self, mock_bot):
        from telegram_bot.handlers.support_handlers import _send_support_draft

        draft = _draft(email=_email(reply_to="user@example.com"))
        sent_msg = MagicMock()
        sent_msg.message_id = 42
        mock_bot.send_message.return_value = sent_msg

        asyncio.run(_send_support_draft(100, draft))

        text = mock_bot.send_message.call_args[0][1]
        assert "Reply-To:" not in text

    @patch("telegram_bot.handlers.support_handlers._support_draft_map", {})
    @patch("telegram_bot.handlers.support_handlers.bot", new_callable=AsyncMock)
    def test_long_body_truncated(self, mock_bot):
        from telegram_bot.handlers.support_handlers import _send_support_draft

        long_body = "x" * 1000
        draft = _draft(email=_email(body=long_body))
        sent_msg = MagicMock()
        sent_msg.message_id = 42
        mock_bot.send_message.return_value = sent_msg

        asyncio.run(_send_support_draft(100, draft))

        text = mock_bot.send_message.call_args[0][1]
        assert "..." in text
        assert long_body not in text


# ===================================================================
#  _send_editorial
# ===================================================================

class TestSendEditorial:

    @patch("telegram_bot.handlers.support_handlers.bot", new_callable=AsyncMock)
    def test_sends_editorial_message(self, mock_bot):
        from telegram_bot.handlers.support_handlers import _send_editorial

        item = _editorial()
        asyncio.run(_send_editorial(100, item))

        mock_bot.send_message.assert_awaited_once()
        call_kwargs = mock_bot.send_message.call_args
        assert call_kwargs[0][0] == 100
        text = call_kwargs[0][1]
        assert "Письмо в редакцию" in text
        assert "user@example.com" in text
        assert "Story pitch" in text
        markup = call_kwargs[1]["reply_markup"]
        buttons = markup.inline_keyboard[0]
        assert len(buttons) == 2

    @patch("telegram_bot.handlers.support_handlers.bot", new_callable=AsyncMock)
    def test_editorial_with_reply(self, mock_bot):
        from telegram_bot.handlers.support_handlers import _send_editorial

        item = _editorial(reply_to_sender="Thanks for reaching out!")
        asyncio.run(_send_editorial(100, item))

        text = mock_bot.send_message.call_args[0][1]
        assert "Автоответ" in text
        assert "Thanks for reaching out!" in text

    @patch("telegram_bot.handlers.support_handlers.bot", new_callable=AsyncMock)
    def test_editorial_without_reply(self, mock_bot):
        from telegram_bot.handlers.support_handlers import _send_editorial

        item = _editorial(reply_to_sender="")
        asyncio.run(_send_editorial(100, item))

        text = mock_bot.send_message.call_args[0][1]
        assert "Автоответ" not in text

    @patch("telegram_bot.handlers.support_handlers.bot", new_callable=AsyncMock)
    def test_editorial_long_body_truncated(self, mock_bot):
        from telegram_bot.handlers.support_handlers import _send_editorial

        item = _editorial(email=_email(body="z" * 1000))
        asyncio.run(_send_editorial(100, item))

        text = mock_bot.send_message.call_args[0][1]
        assert "..." in text

    @patch("telegram_bot.handlers.support_handlers.bot", new_callable=AsyncMock)
    def test_editorial_callback_data_format(self, mock_bot):
        from telegram_bot.handlers.support_handlers import _send_editorial

        item = _editorial(email=_email(uid="my-uid-123"))
        asyncio.run(_send_editorial(100, item))

        markup = mock_bot.send_message.call_args[1]["reply_markup"]
        fwd_btn, skip_btn = markup.inline_keyboard[0]
        assert fwd_btn.callback_data == "editorial:fwd:my-uid-123"
        assert skip_btn.callback_data == "editorial:skip:my-uid-123"
