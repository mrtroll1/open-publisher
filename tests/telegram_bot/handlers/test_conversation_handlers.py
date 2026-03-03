import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _make_message(text: str = "", chat_id: int = 100, user_id: int = 42) -> AsyncMock:
    msg = AsyncMock()
    msg.text = text
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    msg.chat.type = "private"
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.message_id = 10
    msg.reply_to_message = None
    msg.answer = AsyncMock()
    msg.reply = AsyncMock()
    return msg


def _make_state(active=False) -> AsyncMock:
    state = AsyncMock()
    state.get_state.return_value = "SomeState:step" if active else None
    return state


# ===================================================================
#  cmd_nl
# ===================================================================

class TestCmdNl:

    def test_no_args_shows_usage(self):
        from telegram_bot.handlers.conversation_handlers import cmd_nl

        msg = _make_message("/nl")
        state = _make_state()

        asyncio.run(cmd_nl(msg, state))

        msg.answer.assert_awaited_once()
        assert "/nl" in msg.answer.call_args[0][0]

    def test_empty_args_shows_usage(self):
        from telegram_bot.handlers.conversation_handlers import cmd_nl

        msg = _make_message("/nl   ")
        state = _make_state()

        asyncio.run(cmd_nl(msg, state))

        msg.answer.assert_awaited_once()
        assert "/nl" in msg.answer.call_args[0][0]

    @patch("telegram_bot.handlers.conversation_handlers.GeminiGateway")
    @patch("telegram_bot.handlers.conversation_handlers.CommandClassifier")
    def test_classification_error_reports_failure(self, MockClassifier, MockGemini):
        from telegram_bot.handlers.conversation_handlers import cmd_nl

        MockClassifier.return_value.classify.side_effect = Exception("LLM down")

        msg = _make_message("/nl check system health")
        state = _make_state()

        asyncio.run(cmd_nl(msg, state))

        msg.answer.assert_awaited_once()
        assert "не удалось" in msg.answer.call_args[0][0].lower()

    @patch("telegram_bot.handlers.conversation_handlers._send_html", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers._save_turn", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers.GeminiGateway")
    @patch("telegram_bot.handlers.conversation_handlers.CommandClassifier")
    def test_unclassified_sends_reply(self, MockClassifier, MockGemini, mock_save, mock_send_html):
        from telegram_bot.handlers.conversation_handlers import cmd_nl
        from backend.domain.services.command_classifier import ClassificationResult

        MockClassifier.return_value.classify.return_value = ClassificationResult(
            classified=None, reply="Не могу определить команду",
        )
        sent_msg = MagicMock()
        sent_msg.message_id = 11
        mock_send_html.return_value = sent_msg

        msg = _make_message("/nl что-то непонятное")
        state = _make_state()

        asyncio.run(cmd_nl(msg, state))

        mock_send_html.assert_awaited_once()
        assert "Не могу определить команду" in mock_send_html.call_args[0][1]

    @patch("telegram_bot.handlers.conversation_handlers._send_html", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers._save_turn", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers.GeminiGateway")
    @patch("telegram_bot.handlers.conversation_handlers.CommandClassifier")
    def test_unclassified_no_reply_uses_default(self, MockClassifier, MockGemini, mock_save, mock_send_html):
        from telegram_bot.handlers.conversation_handlers import cmd_nl
        from backend.domain.services.command_classifier import ClassificationResult

        MockClassifier.return_value.classify.return_value = ClassificationResult(
            classified=None, reply="",
        )
        sent_msg = MagicMock()
        sent_msg.message_id = 11
        mock_send_html.return_value = sent_msg

        msg = _make_message("/nl что-то непонятное")
        state = _make_state()

        asyncio.run(cmd_nl(msg, state))

        mock_send_html.assert_awaited_once()
        assert "не удалось определить" in mock_send_html.call_args[0][1].lower()

    @patch("telegram_bot.handlers.conversation_handlers._send_html", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers._save_turn", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers.GeminiGateway")
    @patch("telegram_bot.handlers.conversation_handlers.CommandClassifier")
    def test_unclassified_saves_turn_with_nl_fallback(self, MockClassifier, MockGemini, mock_save, mock_send_html):
        from telegram_bot.handlers.conversation_handlers import cmd_nl
        from backend.domain.services.command_classifier import ClassificationResult

        MockClassifier.return_value.classify.return_value = ClassificationResult(
            classified=None, reply="Не знаю",
        )
        sent_msg = MagicMock()
        sent_msg.message_id = 11
        mock_send_html.return_value = sent_msg

        msg = _make_message("/nl что-то непонятное")
        state = _make_state()

        asyncio.run(cmd_nl(msg, state))

        mock_save.assert_awaited_once()
        meta = mock_save.call_args[0][4]
        assert meta["command"] == "nl_fallback"

    @patch("telegram_bot.handlers.support_handlers.send_typing", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.support_handlers._send_html", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.support_handlers._save_turn", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.support_handlers._answer_tech_question")
    @patch("telegram_bot.handlers.conversation_handlers.GeminiGateway")
    @patch("telegram_bot.handlers.conversation_handlers.CommandClassifier")
    def test_classified_dispatches_to_handler(
        self, MockClassifier, MockGemini,
        mock_answer, mock_save, mock_send_html, mock_typing,
    ):
        from telegram_bot.handlers.conversation_handlers import cmd_nl
        from backend.domain.services.command_classifier import ClassificationResult, ClassifiedCommand

        MockClassifier.return_value.classify.return_value = ClassificationResult(
            classified=ClassifiedCommand(command="support", args="как поменять пароль?"),
            reply="",
        )
        mock_answer.return_value = "Вот ответ"
        sent_msg = MagicMock()
        sent_msg.message_id = 11
        mock_send_html.return_value = sent_msg

        msg = _make_message("/nl как поменять пароль?")
        state = _make_state()

        asyncio.run(cmd_nl(msg, state))

        # Verify _answer_tech_question was called (cmd_support delegates to it)
        mock_answer.assert_called_once()

    @patch("telegram_bot.handlers.conversation_handlers.GeminiGateway")
    @patch("telegram_bot.handlers.conversation_handlers.CommandClassifier")
    def test_classified_unknown_handler_reports_not_found(self, MockClassifier, MockGemini):
        from telegram_bot.handlers.conversation_handlers import cmd_nl
        from backend.domain.services.command_classifier import ClassificationResult, ClassifiedCommand

        MockClassifier.return_value.classify.return_value = ClassificationResult(
            classified=ClassifiedCommand(command="nonexistent_cmd", args=""),
            reply="",
        )

        msg = _make_message("/nl сделай что-то невозможное")
        state = _make_state()

        asyncio.run(cmd_nl(msg, state))

        msg.answer.assert_awaited_once()
        assert "не найдена" in msg.answer.call_args[0][0].lower()

    @patch("telegram_bot.handlers.conversation_handlers.GeminiGateway")
    @patch("telegram_bot.handlers.conversation_handlers.CommandClassifier")
    def test_classified_rewrites_message_text(self, MockClassifier, MockGemini):
        from telegram_bot.handlers.conversation_handlers import cmd_nl
        from backend.domain.services.command_classifier import ClassificationResult, ClassifiedCommand

        # When args is empty, cmd_nl uses the original user text as args
        MockClassifier.return_value.classify.return_value = ClassificationResult(
            classified=ClassifiedCommand(command="health", args=""),
            reply="",
        )

        msg = _make_message("/nl проверь здоровье системы")
        state = _make_state()

        captured_texts = []

        async def fake_health(m, s):
            captured_texts.append(m.text)

        # _GROUP_COMMAND_HANDLERS is imported lazily inside cmd_nl from group_handlers
        with patch("telegram_bot.handlers.group_handlers._GROUP_COMMAND_HANDLERS",
                    {"health": fake_health}):
            asyncio.run(cmd_nl(msg, state))

        # When classifier returns empty args, text is "проверь здоровье системы" (original input)
        assert captured_texts == ["/health проверь здоровье системы"]
        # Text should be restored after dispatch
        assert msg.text == "/nl проверь здоровье системы"

    @patch("telegram_bot.handlers.conversation_handlers.GeminiGateway")
    @patch("telegram_bot.handlers.conversation_handlers.CommandClassifier")
    def test_classified_restores_text_on_handler_error(self, MockClassifier, MockGemini):
        from telegram_bot.handlers.conversation_handlers import cmd_nl
        from backend.domain.services.command_classifier import ClassificationResult, ClassifiedCommand

        MockClassifier.return_value.classify.return_value = ClassificationResult(
            classified=ClassifiedCommand(command="health", args=""),
            reply="",
        )

        msg = _make_message("/nl проверь здоровье")
        state = _make_state()

        async def broken_health(m, s):
            raise RuntimeError("handler crash")

        with patch("telegram_bot.handlers.group_handlers._GROUP_COMMAND_HANDLERS",
                    {"health": broken_health}):
            with pytest.raises(RuntimeError):
                asyncio.run(cmd_nl(msg, state))

        # Text should still be restored
        assert msg.text == "/nl проверь здоровье"


# ===================================================================
#  _handle_nl_reply (additional cases for the new module)
# ===================================================================

class TestHandleNlReplyNewModule:

    @patch("telegram_bot.handlers.conversation_handlers.generate_nl_reply")
    @patch("telegram_bot.handlers.conversation_handlers.build_conversation_context")
    @patch("telegram_bot.handlers.conversation_handlers._send_html", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers._save_turn", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers.send_typing", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers._get_retriever")
    @patch("telegram_bot.handlers.conversation_handlers._db")
    def test_fsm_active_returns_false(
        self, mock_db, mock_get_retriever, mock_typing,
        mock_save, mock_send_html, mock_build, mock_generate,
    ):
        from telegram_bot.handlers.conversation_handlers import _handle_nl_reply

        msg = AsyncMock()
        msg.text = "Hello"
        msg.reply_to_message = MagicMock()
        msg.reply_to_message.from_user.is_bot = True

        state = _make_state(active=True)
        result = asyncio.run(_handle_nl_reply(msg, state))
        assert result is False

    @patch("telegram_bot.handlers.conversation_handlers.generate_nl_reply")
    @patch("telegram_bot.handlers.conversation_handlers.build_conversation_context")
    @patch("telegram_bot.handlers.conversation_handlers._send_html", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers._save_turn", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers.send_typing", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers._get_retriever")
    @patch("telegram_bot.handlers.conversation_handlers._db")
    def test_no_reply_returns_false(
        self, mock_db, mock_get_retriever, mock_typing,
        mock_save, mock_send_html, mock_build, mock_generate,
    ):
        from telegram_bot.handlers.conversation_handlers import _handle_nl_reply

        msg = AsyncMock()
        msg.text = "Hello"
        msg.reply_to_message = None

        state = _make_state()
        result = asyncio.run(_handle_nl_reply(msg, state))
        assert result is False

    @patch("telegram_bot.handlers.conversation_handlers.generate_nl_reply")
    @patch("telegram_bot.handlers.conversation_handlers.build_conversation_context")
    @patch("telegram_bot.handlers.conversation_handlers._send_html", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers._save_turn", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers.send_typing", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers._get_retriever")
    @patch("telegram_bot.handlers.conversation_handlers._db")
    def test_reply_not_from_bot_returns_false(
        self, mock_db, mock_get_retriever, mock_typing,
        mock_save, mock_send_html, mock_build, mock_generate,
    ):
        from telegram_bot.handlers.conversation_handlers import _handle_nl_reply

        msg = AsyncMock()
        msg.text = "Hello"
        msg.reply_to_message = MagicMock()
        msg.reply_to_message.from_user.is_bot = False

        state = _make_state()
        result = asyncio.run(_handle_nl_reply(msg, state))
        assert result is False

    @patch("telegram_bot.handlers.conversation_handlers.GeminiGateway")
    @patch("telegram_bot.handlers.conversation_handlers.generate_nl_reply")
    @patch("telegram_bot.handlers.conversation_handlers.build_conversation_context")
    @patch("telegram_bot.handlers.conversation_handlers._send_html", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers._save_turn", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers.send_typing", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers._get_retriever")
    @patch("telegram_bot.handlers.conversation_handlers._db")
    def test_happy_path(
        self, mock_db, mock_get_retriever, mock_typing,
        mock_save, mock_send_html, mock_build, mock_generate, MockGemini,
    ):
        from telegram_bot.handlers.conversation_handlers import _handle_nl_reply

        msg = AsyncMock()
        msg.text = "Какая цена подписки?"
        msg.chat.id = 100
        msg.from_user.id = 42
        msg.message_id = 10
        msg.reply_to_message = MagicMock()
        msg.reply_to_message.message_id = 9
        msg.reply_to_message.text = "Задайте вопрос"
        msg.reply_to_message.from_user = MagicMock()
        msg.reply_to_message.from_user.is_bot = True

        mock_build.return_value = ([{"role": "user", "content": "hi"}], "parent-id")
        mock_generate.return_value = "Подписка стоит 500 руб."

        sent = MagicMock()
        sent.message_id = 11
        mock_send_html.return_value = sent

        state = _make_state()
        result = asyncio.run(_handle_nl_reply(msg, state))

        assert result is True
        mock_typing.assert_awaited_once()
        mock_send_html.assert_awaited_once()
        mock_save.assert_awaited_once()

    @patch("telegram_bot.handlers.conversation_handlers.GeminiGateway")
    @patch("telegram_bot.handlers.conversation_handlers.generate_nl_reply")
    @patch("telegram_bot.handlers.conversation_handlers.build_conversation_context")
    @patch("telegram_bot.handlers.conversation_handlers._send_html", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers._save_turn", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers.send_typing", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers._get_retriever")
    @patch("telegram_bot.handlers.conversation_handlers._db")
    def test_teaching_keyword_stores(
        self, mock_db, mock_get_retriever, mock_typing,
        mock_save, mock_send_html, mock_build, mock_generate, MockGemini,
    ):
        from telegram_bot.handlers.conversation_handlers import _handle_nl_reply

        retriever = MagicMock()
        mock_get_retriever.return_value = retriever

        msg = AsyncMock()
        msg.text = "Запомни: клиентам отвечаем на русском"
        msg.chat.id = 100
        msg.from_user.id = 42
        msg.message_id = 10
        msg.reply_to_message = MagicMock()
        msg.reply_to_message.message_id = 9
        msg.reply_to_message.text = "Ок"
        msg.reply_to_message.from_user = MagicMock()
        msg.reply_to_message.from_user.is_bot = True

        mock_build.return_value = ([], None)
        mock_generate.return_value = "Запомнил!"
        mock_send_html.return_value = MagicMock(message_id=11)

        state = _make_state()
        result = asyncio.run(_handle_nl_reply(msg, state))

        assert result is True
        retriever.store_teaching.assert_called_once()
