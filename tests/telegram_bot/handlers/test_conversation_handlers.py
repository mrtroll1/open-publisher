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


def _mock_thinking_message_class():
    """Return a mock ThinkingMessage class that acts as a pass-through async context manager."""
    sent = MagicMock(message_id=11)
    thinking = AsyncMock()
    thinking.finish_long = AsyncMock(return_value=sent)
    thinking.finish = AsyncMock(return_value=sent)
    thinking.update = AsyncMock()
    thinking.__aenter__ = AsyncMock(return_value=thinking)
    thinking.__aexit__ = AsyncMock(return_value=False)
    cls = MagicMock(return_value=thinking)
    cls._instance = thinking
    cls._sent = sent
    return cls


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

    @patch("telegram_bot.handlers.conversation_handlers.resolve_entity_context", return_value="")
    @patch("telegram_bot.handlers.conversation_handlers.resolve_environment", return_value=("", None))
    @patch("telegram_bot.handlers.conversation_handlers.generate_nl_reply")
    @patch("telegram_bot.handlers.conversation_handlers._get_retriever")
    @patch("telegram_bot.handlers.conversation_handlers._save_turn", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers.ThinkingMessage")
    @patch("telegram_bot.handlers.conversation_handlers.GeminiGateway")
    @patch("telegram_bot.handlers.conversation_handlers.CommandClassifier")
    def test_unclassified_generates_rag_reply(
        self, MockClassifier, MockGemini, MockThinking,
        mock_save, mock_get_retriever, mock_generate,
        mock_resolve_env, mock_resolve_entity,
    ):
        from telegram_bot.handlers.conversation_handlers import cmd_nl
        from backend.domain.services.command_classifier import ClassificationResult

        mock_tm = _mock_thinking_message_class()
        MockThinking.side_effect = mock_tm

        MockClassifier.return_value.classify.return_value = ClassificationResult(
            classified=None, reply="",
        )
        mock_generate.return_value = "Вот что я знаю по этому вопросу."

        msg = _make_message("/nl что-то непонятное")
        state = _make_state()

        asyncio.run(cmd_nl(msg, state))

        mock_generate.assert_called_once()
        mock_tm._instance.finish_long.assert_awaited_once()
        assert "Вот что я знаю" in mock_tm._instance.finish_long.call_args[0][0]

    @patch("telegram_bot.handlers.conversation_handlers.resolve_entity_context", return_value="")
    @patch("telegram_bot.handlers.conversation_handlers.resolve_environment", return_value=("", None))
    @patch("telegram_bot.handlers.conversation_handlers.generate_nl_reply")
    @patch("telegram_bot.handlers.conversation_handlers._get_retriever")
    @patch("telegram_bot.handlers.conversation_handlers._save_turn", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers.ThinkingMessage")
    @patch("telegram_bot.handlers.conversation_handlers.GeminiGateway")
    @patch("telegram_bot.handlers.conversation_handlers.CommandClassifier")
    def test_unclassified_saves_turn_with_nl_rag(
        self, MockClassifier, MockGemini, MockThinking,
        mock_save, mock_get_retriever, mock_generate,
        mock_resolve_env, mock_resolve_entity,
    ):
        from telegram_bot.handlers.conversation_handlers import cmd_nl
        from backend.domain.services.command_classifier import ClassificationResult

        mock_tm = _mock_thinking_message_class()
        MockThinking.side_effect = mock_tm

        MockClassifier.return_value.classify.return_value = ClassificationResult(
            classified=None, reply="",
        )
        mock_generate.return_value = "Ответ"

        msg = _make_message("/nl что-то непонятное")
        state = _make_state()

        asyncio.run(cmd_nl(msg, state))

        mock_save.assert_awaited_once()
        meta = mock_save.call_args[0][4]
        assert meta["command"] == "nl_rag"

    @patch("telegram_bot.handlers.support_handlers.ThinkingMessage")
    @patch("telegram_bot.handlers.support_handlers._save_turn", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.support_handlers._answer_tech_question")
    @patch("telegram_bot.handlers.conversation_handlers.GeminiGateway")
    @patch("telegram_bot.handlers.conversation_handlers.CommandClassifier")
    def test_classified_dispatches_to_handler(
        self, MockClassifier, MockGemini,
        mock_answer, mock_save, MockThinking,
    ):
        from telegram_bot.handlers.conversation_handlers import cmd_nl
        from backend.domain.services.command_classifier import ClassificationResult, ClassifiedCommand

        mock_tm = _mock_thinking_message_class()
        MockThinking.side_effect = mock_tm

        MockClassifier.return_value.classify.return_value = ClassificationResult(
            classified=ClassifiedCommand(command="support", args="как поменять пароль?"),
            reply="",
        )
        mock_answer.return_value = "Вот ответ"

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
        with patch("telegram_bot.router._GROUP_COMMAND_HANDLERS",
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

        with patch("telegram_bot.router._GROUP_COMMAND_HANDLERS",
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

    @patch("telegram_bot.handlers.conversation_handlers.resolve_entity_context", return_value="")
    @patch("telegram_bot.handlers.conversation_handlers.resolve_environment", return_value=("", None))
    @patch("telegram_bot.handlers.conversation_handlers.GeminiGateway")
    @patch("telegram_bot.handlers.conversation_handlers.generate_nl_reply")
    @patch("telegram_bot.handlers.conversation_handlers.build_conversation_context")
    @patch("telegram_bot.handlers.conversation_handlers._save_turn", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers.ThinkingMessage")
    @patch("telegram_bot.handlers.conversation_handlers._get_retriever")
    @patch("telegram_bot.handlers.conversation_handlers._db")
    def test_happy_path(
        self, mock_db, mock_get_retriever, MockThinking,
        mock_save, mock_build, mock_generate, MockGemini,
        mock_resolve_env, mock_resolve_entity,
    ):
        from telegram_bot.handlers.conversation_handlers import _handle_nl_reply

        mock_tm = _mock_thinking_message_class()
        MockThinking.side_effect = mock_tm

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

        state = _make_state()
        result = asyncio.run(_handle_nl_reply(msg, state))

        assert result is True
        mock_tm._instance.finish_long.assert_awaited_once()
        mock_save.assert_awaited_once()

    @patch("telegram_bot.handlers.conversation_handlers.is_admin", return_value=True)
    @patch("telegram_bot.handlers.conversation_handlers.resolve_entity_context", return_value="")
    @patch("telegram_bot.handlers.conversation_handlers.resolve_environment", return_value=("", None))
    @patch("telegram_bot.handlers.conversation_handlers.GeminiGateway")
    @patch("telegram_bot.handlers.conversation_handlers.generate_nl_reply")
    @patch("telegram_bot.handlers.conversation_handlers.build_conversation_context")
    @patch("telegram_bot.handlers.conversation_handlers._save_turn", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers.ThinkingMessage")
    @patch("telegram_bot.handlers.conversation_handlers._get_retriever")
    @patch("telegram_bot.handlers.conversation_handlers._db")
    @patch("telegram_bot.handlers.conversation_handlers._memory")
    def test_teaching_keyword_stores(
        self, mock_memory, mock_db, mock_get_retriever, MockThinking,
        mock_save, mock_build, mock_generate, MockGemini,
        mock_resolve_env, mock_resolve_entity, mock_is_admin,
    ):
        from telegram_bot.handlers.conversation_handlers import _handle_nl_reply

        mock_tm = _mock_thinking_message_class()
        MockThinking.side_effect = mock_tm

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

        state = _make_state()
        result = asyncio.run(_handle_nl_reply(msg, state))

        assert result is True
        mock_memory.teach.assert_called_once()

    @patch("telegram_bot.handlers.conversation_handlers.is_admin", return_value=False)
    @patch("telegram_bot.handlers.conversation_handlers.resolve_entity_context", return_value="")
    @patch("telegram_bot.handlers.conversation_handlers.resolve_environment", return_value=("", None))
    @patch("telegram_bot.handlers.conversation_handlers.GeminiGateway")
    @patch("telegram_bot.handlers.conversation_handlers.generate_nl_reply")
    @patch("telegram_bot.handlers.conversation_handlers.build_conversation_context")
    @patch("telegram_bot.handlers.conversation_handlers._save_turn", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers.ThinkingMessage")
    @patch("telegram_bot.handlers.conversation_handlers._get_retriever")
    @patch("telegram_bot.handlers.conversation_handlers._db")
    @patch("telegram_bot.handlers.conversation_handlers._memory")
    def test_teaching_keywords_ignored_for_non_admin(
        self, mock_memory, mock_db, mock_get_retriever, MockThinking,
        mock_save, mock_build, mock_generate, MockGemini,
        mock_resolve_env, mock_resolve_entity, mock_is_admin,
    ):
        from telegram_bot.handlers.conversation_handlers import _handle_nl_reply

        mock_tm = _mock_thinking_message_class()
        MockThinking.side_effect = mock_tm

        msg = AsyncMock()
        msg.text = "Запомни: клиентам отвечаем на русском"
        msg.chat.id = 100
        msg.from_user.id = 999
        msg.message_id = 10
        msg.reply_to_message = MagicMock()
        msg.reply_to_message.message_id = 9
        msg.reply_to_message.text = "Ок"
        msg.reply_to_message.from_user = MagicMock()
        msg.reply_to_message.from_user.is_bot = True

        mock_build.return_value = ([], None)
        mock_generate.return_value = "Ответ"

        state = _make_state()
        result = asyncio.run(_handle_nl_reply(msg, state))

        assert result is True
        mock_memory.teach.assert_not_called()

    @patch("telegram_bot.handlers.conversation_handlers.resolve_entity_context", return_value="")
    @patch("telegram_bot.handlers.conversation_handlers.resolve_environment",
           return_value=("Ты бот редакции", ["editorial", "general"]))
    @patch("telegram_bot.handlers.conversation_handlers.GeminiGateway")
    @patch("telegram_bot.handlers.conversation_handlers.generate_nl_reply")
    @patch("telegram_bot.handlers.conversation_handlers.build_conversation_context")
    @patch("telegram_bot.handlers.conversation_handlers._save_turn", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers.ThinkingMessage")
    @patch("telegram_bot.handlers.conversation_handlers._get_retriever")
    @patch("telegram_bot.handlers.conversation_handlers._db")
    def test_environment_resolved_and_passed(
        self, mock_db, mock_get_retriever, MockThinking,
        mock_save, mock_build, mock_generate, MockGemini,
        mock_resolve_env, mock_resolve_entity,
    ):
        from telegram_bot.handlers.conversation_handlers import _handle_nl_reply

        mock_tm = _mock_thinking_message_class()
        MockThinking.side_effect = mock_tm

        msg = AsyncMock()
        msg.text = "Вопрос"
        msg.chat.id = 100
        msg.from_user.id = 42
        msg.message_id = 10
        msg.reply_to_message = MagicMock()
        msg.reply_to_message.message_id = 9
        msg.reply_to_message.text = "Ответ"
        msg.reply_to_message.from_user = MagicMock()
        msg.reply_to_message.from_user.is_bot = True

        mock_build.return_value = ("history", "parent-id")
        mock_generate.return_value = "Ответ бота"

        state = _make_state()
        asyncio.run(_handle_nl_reply(msg, state))

        mock_resolve_env.assert_called_once_with(100)
        call_kwargs = mock_generate.call_args
        assert call_kwargs[1]["environment"] == "Ты бот редакции"
        assert call_kwargs[1]["allowed_domains"] == ["editorial", "general"]


# ===================================================================
#  cmd_nl environment resolution
# ===================================================================

class TestCmdNlEnvironment:

    @patch("telegram_bot.handlers.conversation_handlers.resolve_entity_context", return_value="")
    @patch("telegram_bot.handlers.conversation_handlers.resolve_environment",
           return_value=("env context", ["domain1"]))
    @patch("telegram_bot.handlers.conversation_handlers.generate_nl_reply")
    @patch("telegram_bot.handlers.conversation_handlers._get_retriever")
    @patch("telegram_bot.handlers.conversation_handlers._save_turn", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers.ThinkingMessage")
    @patch("telegram_bot.handlers.conversation_handlers.GeminiGateway")
    @patch("telegram_bot.handlers.conversation_handlers.CommandClassifier")
    def test_cmd_nl_passes_environment(
        self, MockClassifier, MockGemini, MockThinking,
        mock_save, mock_get_retriever, mock_generate,
        mock_resolve_env, mock_resolve_entity,
    ):
        from telegram_bot.handlers.conversation_handlers import cmd_nl
        from backend.domain.services.command_classifier import ClassificationResult

        mock_tm = _mock_thinking_message_class()
        MockThinking.side_effect = mock_tm

        MockClassifier.return_value.classify.return_value = ClassificationResult(
            classified=None, reply="",
        )
        mock_generate.return_value = "Ответ"

        msg = _make_message("/nl вопрос")
        state = _make_state()

        asyncio.run(cmd_nl(msg, state))

        mock_resolve_env.assert_called_once_with(msg.chat.id)
        call_kwargs = mock_generate.call_args
        assert call_kwargs[1]["environment"] == "env context"
        assert call_kwargs[1]["allowed_domains"] == ["domain1"]


# ===================================================================
#  cmd_env
# ===================================================================

class TestCmdEnv:

    @patch("telegram_bot.handlers.conversation_handlers._send", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers._db")
    @patch("telegram_bot.handlers.conversation_handlers._memory")
    def test_cmd_env_lists_all(self, mock_memory, mock_db, mock_send):
        from telegram_bot.handlers.conversation_handlers import cmd_env

        mock_memory.list_environments.return_value = [
            {
                "name": "admin_dm",
                "description": "Admin chat",
                "system_context": "Full access.",
                "allowed_domains": None,
            },
            {
                "name": "editorial_group",
                "description": "Editorial",
                "system_context": "Group context.",
                "allowed_domains": ["tech_support", "editorial"],
            },
        ]
        mock_db.get_bindings_for_environment.return_value = []

        msg = _make_message("/env")
        state = _make_state()
        asyncio.run(cmd_env(msg, state))

        mock_memory.list_environments.assert_called_once()
        mock_send.assert_awaited_once()
        text = mock_send.call_args[0][1]
        assert "admin_dm" in text
        assert "editorial_group" in text

    @patch("telegram_bot.handlers.conversation_handlers._send", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers._db")
    @patch("telegram_bot.handlers.conversation_handlers._memory")
    def test_cmd_env_shows_details(self, mock_memory, mock_db, mock_send):
        from telegram_bot.handlers.conversation_handlers import cmd_env

        mock_memory.get_environment.return_value = {
            "name": "admin_dm",
            "description": "Admin chat",
            "system_context": "Full access context.",
            "allowed_domains": ["payments"],
        }
        mock_db.get_bindings_for_environment.return_value = [12345, 67890]

        msg = _make_message("/env admin_dm")
        state = _make_state()
        asyncio.run(cmd_env(msg, state))

        mock_memory.get_environment.assert_called_once_with(name="admin_dm")
        mock_send.assert_awaited_once()
        text = mock_send.call_args[0][1]
        assert "admin_dm" in text
        assert "Full access context." in text
        assert "12345" in text
        assert "67890" in text

    @patch("telegram_bot.handlers.conversation_handlers._memory")
    def test_cmd_env_not_found(self, mock_memory):
        from telegram_bot.handlers.conversation_handlers import cmd_env

        mock_memory.get_environment.return_value = None

        msg = _make_message("/env nonexistent")
        state = _make_state()
        asyncio.run(cmd_env(msg, state))

        msg.answer.assert_awaited_once()
        assert "не найдено" in msg.answer.call_args[0][0].lower()


# ===================================================================
#  cmd_env_edit
# ===================================================================

class TestCmdEnvEdit:

    @patch("telegram_bot.handlers.conversation_handlers._memory")
    def test_cmd_env_edit_updates_system_context(self, mock_memory):
        from telegram_bot.handlers.conversation_handlers import cmd_env_edit

        mock_memory.update_environment.return_value = True

        msg = _make_message("/env_edit admin_dm system_context New context here")
        state = _make_state()
        asyncio.run(cmd_env_edit(msg, state))

        mock_memory.update_environment.assert_called_once_with(
            "admin_dm", system_context="New context here",
        )
        msg.answer.assert_awaited_once()
        assert "обновлено" in msg.answer.call_args[0][0].lower()

    @patch("telegram_bot.handlers.conversation_handlers._memory")
    def test_cmd_env_edit_updates_allowed_domains(self, mock_memory):
        from telegram_bot.handlers.conversation_handlers import cmd_env_edit

        mock_memory.update_environment.return_value = True

        msg = _make_message("/env_edit editorial_group allowed_domains tech_support, editorial, payments")
        state = _make_state()
        asyncio.run(cmd_env_edit(msg, state))

        mock_memory.update_environment.assert_called_once_with(
            "editorial_group",
            allowed_domains=["tech_support", "editorial", "payments"],
        )

    @patch("telegram_bot.handlers.conversation_handlers._memory")
    def test_cmd_env_edit_invalid_field(self, mock_memory):
        from telegram_bot.handlers.conversation_handlers import cmd_env_edit

        msg = _make_message("/env_edit admin_dm bogus_field value")
        state = _make_state()
        asyncio.run(cmd_env_edit(msg, state))

        mock_memory.update_environment.assert_not_called()
        msg.answer.assert_awaited_once()

    def test_cmd_env_edit_no_args_shows_usage(self):
        from telegram_bot.handlers.conversation_handlers import cmd_env_edit

        msg = _make_message("/env_edit")
        state = _make_state()
        asyncio.run(cmd_env_edit(msg, state))

        msg.answer.assert_awaited_once()
        assert "env_edit" in msg.answer.call_args[0][0].lower()


# ===================================================================
#  cmd_env_bind
# ===================================================================

class TestCmdEnvBind:

    @patch("telegram_bot.handlers.conversation_handlers._db")
    @patch("telegram_bot.handlers.conversation_handlers._memory")
    def test_cmd_env_bind_binds_current_chat(self, mock_memory, mock_db):
        from telegram_bot.handlers.conversation_handlers import cmd_env_bind

        mock_memory.get_environment.return_value = {
            "name": "editorial_group",
            "description": "Editorial",
            "system_context": "Group context.",
            "allowed_domains": ["editorial"],
        }

        msg = _make_message("/env_bind editorial_group", chat_id=555)
        state = _make_state()
        asyncio.run(cmd_env_bind(msg, state))

        mock_memory.get_environment.assert_called_once_with(name="editorial_group")
        mock_db.bind_chat.assert_called_once_with(555, "editorial_group")
        msg.answer.assert_awaited_once()
        assert "editorial_group" in msg.answer.call_args[0][0]

    @patch("telegram_bot.handlers.conversation_handlers._db")
    @patch("telegram_bot.handlers.conversation_handlers._memory")
    def test_cmd_env_bind_not_found(self, mock_memory, mock_db):
        from telegram_bot.handlers.conversation_handlers import cmd_env_bind

        mock_memory.get_environment.return_value = None

        msg = _make_message("/env_bind nonexistent")
        state = _make_state()
        asyncio.run(cmd_env_bind(msg, state))

        mock_db.bind_chat.assert_not_called()
        msg.answer.assert_awaited_once()
        assert "не найдено" in msg.answer.call_args[0][0].lower()

    def test_cmd_env_bind_no_args_shows_usage(self):
        from telegram_bot.handlers.conversation_handlers import cmd_env_bind

        msg = _make_message("/env_bind")
        state = _make_state()
        asyncio.run(cmd_env_bind(msg, state))

        msg.answer.assert_awaited_once()
        assert "env_bind" in msg.answer.call_args[0][0].lower()


# ===================================================================
#  cmd_env_create
# ===================================================================

class TestCmdEnvCreate:

    @patch("telegram_bot.handlers.conversation_handlers._db")
    def test_cmd_env_create_creates_environment(self, mock_db):
        from telegram_bot.handlers.conversation_handlers import cmd_env_create

        msg = _make_message("/env_create test_env Test environment")
        state = _make_state()
        asyncio.run(cmd_env_create(msg, state))

        mock_db.save_environment.assert_called_once_with("test_env", "Test environment", "")
        msg.answer.assert_awaited_once()
        assert "test_env" in msg.answer.call_args[0][0]

    def test_cmd_env_create_no_args_shows_usage(self):
        from telegram_bot.handlers.conversation_handlers import cmd_env_create

        msg = _make_message("/env_create")
        state = _make_state()
        asyncio.run(cmd_env_create(msg, state))

        msg.answer.assert_awaited_once()
        assert "env_create" in msg.answer.call_args[0][0].lower()

    def test_cmd_env_create_missing_description_shows_usage(self):
        from telegram_bot.handlers.conversation_handlers import cmd_env_create

        msg = _make_message("/env_create test_env")
        state = _make_state()
        asyncio.run(cmd_env_create(msg, state))

        msg.answer.assert_awaited_once()
        assert "env_create" in msg.answer.call_args[0][0].lower()


# ===================================================================
#  cmd_env_unbind
# ===================================================================

class TestCmdEnvUnbind:

    @patch("telegram_bot.handlers.conversation_handlers._db")
    def test_cmd_env_unbind_unbinds_chat(self, mock_db):
        from telegram_bot.handlers.conversation_handlers import cmd_env_unbind

        msg = _make_message("/env_unbind", chat_id=555)
        state = _make_state()
        asyncio.run(cmd_env_unbind(msg, state))

        mock_db.unbind_chat.assert_called_once_with(555)
        msg.answer.assert_awaited_once()
        assert "отвязан" in msg.answer.call_args[0][0].lower()


# ===================================================================
#  cmd_entity
# ===================================================================

class TestCmdEntity:

    @patch("telegram_bot.handlers.conversation_handlers._send", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers._db")
    def test_cmd_entity_lists_all(self, mock_db, mock_send):
        from telegram_bot.handlers.conversation_handlers import cmd_entity

        mock_db.list_entities.return_value = [
            {"id": "1", "kind": "person", "name": "Alice", "external_ids": {}},
            {"id": "2", "kind": "person", "name": "Bob", "external_ids": {}},
            {"id": "3", "kind": "organization", "name": "Acme", "external_ids": {}},
        ]

        msg = _make_message("/entity")
        state = _make_state()
        asyncio.run(cmd_entity(msg, state))

        mock_db.list_entities.assert_called_once()
        mock_send.assert_awaited_once()
        text = mock_send.call_args[0][1]
        assert "person" in text
        assert "Alice" in text
        assert "Bob" in text
        assert "organization" in text
        assert "Acme" in text

    @patch("telegram_bot.handlers.conversation_handlers._db")
    def test_cmd_entity_empty(self, mock_db):
        from telegram_bot.handlers.conversation_handlers import cmd_entity

        mock_db.list_entities.return_value = []

        msg = _make_message("/entity")
        state = _make_state()
        asyncio.run(cmd_entity(msg, state))

        msg.answer.assert_awaited_once()
        assert "не найдено" in msg.answer.call_args[0][0].lower()

    @patch("telegram_bot.handlers.conversation_handlers._send", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers._db")
    def test_cmd_entity_shows_details(self, mock_db, mock_send):
        from telegram_bot.handlers.conversation_handlers import cmd_entity

        mock_db.find_entities_by_name.return_value = [
            {
                "id": "abc-123",
                "kind": "person",
                "name": "Alice Smith",
                "external_ids": {"telegram_user_id": "42"},
            },
        ]

        msg = _make_message("/entity Alice")
        state = _make_state()
        asyncio.run(cmd_entity(msg, state))

        mock_db.find_entities_by_name.assert_called_once_with("Alice")
        mock_send.assert_awaited_once()
        text = mock_send.call_args[0][1]
        assert "Alice Smith" in text
        assert "person" in text
        assert "abc-123" in text
        assert "telegram_user_id=42" in text

    @patch("telegram_bot.handlers.conversation_handlers._db")
    def test_cmd_entity_search_not_found(self, mock_db):
        from telegram_bot.handlers.conversation_handlers import cmd_entity

        mock_db.find_entities_by_name.return_value = []

        msg = _make_message("/entity nonexistent")
        state = _make_state()
        asyncio.run(cmd_entity(msg, state))

        msg.answer.assert_awaited_once()
        assert "не найден" in msg.answer.call_args[0][0].lower()


# ===================================================================
#  cmd_entity_add
# ===================================================================

class TestCmdEntityAdd:

    @patch("telegram_bot.handlers.conversation_handlers._memory")
    def test_cmd_entity_add_creates(self, mock_memory):
        from telegram_bot.handlers.conversation_handlers import cmd_entity_add

        mock_memory.add_entity.return_value = "new-id"

        msg = _make_message("/entity_add person Alice Smith")
        state = _make_state()
        asyncio.run(cmd_entity_add(msg, state))

        mock_memory.add_entity.assert_called_once_with("person", "Alice Smith")
        msg.answer.assert_awaited_once()
        text = msg.answer.call_args[0][0]
        assert "Alice Smith" in text
        assert "person" in text

    @patch("telegram_bot.handlers.conversation_handlers._memory")
    def test_cmd_entity_add_invalid_kind(self, mock_memory):
        from telegram_bot.handlers.conversation_handlers import cmd_entity_add

        msg = _make_message("/entity_add alien Test Name")
        state = _make_state()
        asyncio.run(cmd_entity_add(msg, state))

        mock_memory.add_entity.assert_not_called()
        msg.answer.assert_awaited_once()
        assert "неизвестный" in msg.answer.call_args[0][0].lower()

    def test_cmd_entity_add_no_args_shows_usage(self):
        from telegram_bot.handlers.conversation_handlers import cmd_entity_add

        msg = _make_message("/entity_add")
        state = _make_state()
        asyncio.run(cmd_entity_add(msg, state))

        msg.answer.assert_awaited_once()
        assert "entity_add" in msg.answer.call_args[0][0].lower()

    def test_cmd_entity_add_missing_name_shows_usage(self):
        from telegram_bot.handlers.conversation_handlers import cmd_entity_add

        msg = _make_message("/entity_add person")
        state = _make_state()
        asyncio.run(cmd_entity_add(msg, state))

        msg.answer.assert_awaited_once()
        assert "entity_add" in msg.answer.call_args[0][0].lower()


# ===================================================================
#  cmd_entity_link
# ===================================================================

class TestCmdEntityLink:

    @patch("telegram_bot.handlers.conversation_handlers._db")
    @patch("telegram_bot.handlers.conversation_handlers._memory")
    def test_cmd_entity_link_updates(self, mock_memory, mock_db):
        from telegram_bot.handlers.conversation_handlers import cmd_entity_link

        mock_memory.find_entity.return_value = {
            "id": "e-1", "name": "Alice", "external_ids": {"old_key": "old_val"},
        }
        mock_db.update_entity.return_value = True

        msg = _make_message("/entity_link Alice telegram_user_id=123")
        state = _make_state()
        asyncio.run(cmd_entity_link(msg, state))

        mock_memory.find_entity.assert_called_once_with(query="Alice")
        mock_db.update_entity.assert_called_once_with(
            "e-1", external_ids={"old_key": "old_val", "telegram_user_id": "123"},
        )
        msg.answer.assert_awaited_once()
        assert "Alice" in msg.answer.call_args[0][0]

    @patch("telegram_bot.handlers.conversation_handlers._memory")
    def test_cmd_entity_link_entity_not_found(self, mock_memory):
        from telegram_bot.handlers.conversation_handlers import cmd_entity_link

        mock_memory.find_entity.return_value = None

        msg = _make_message("/entity_link Unknown telegram_user_id=123")
        state = _make_state()
        asyncio.run(cmd_entity_link(msg, state))

        msg.answer.assert_awaited_once()
        assert "не найден" in msg.answer.call_args[0][0].lower()

    def test_cmd_entity_link_no_args_shows_usage(self):
        from telegram_bot.handlers.conversation_handlers import cmd_entity_link

        msg = _make_message("/entity_link")
        state = _make_state()
        asyncio.run(cmd_entity_link(msg, state))

        msg.answer.assert_awaited_once()
        assert "entity_link" in msg.answer.call_args[0][0].lower()

    def test_cmd_entity_link_no_kv_pairs_shows_usage(self):
        from telegram_bot.handlers.conversation_handlers import cmd_entity_link

        msg = _make_message("/entity_link Alice")
        state = _make_state()
        asyncio.run(cmd_entity_link(msg, state))

        msg.answer.assert_awaited_once()
        assert "entity_link" in msg.answer.call_args[0][0].lower()

    @patch("telegram_bot.handlers.conversation_handlers._db")
    @patch("telegram_bot.handlers.conversation_handlers._memory")
    def test_cmd_entity_link_merges_with_existing(self, mock_memory, mock_db):
        from telegram_bot.handlers.conversation_handlers import cmd_entity_link

        mock_memory.find_entity.return_value = {
            "id": "e-1", "name": "Alice", "external_ids": {"email": "a@b.com"},
        }
        mock_db.update_entity.return_value = True

        msg = _make_message("/entity_link Alice telegram_user_id=99 slack_id=abc")
        state = _make_state()
        asyncio.run(cmd_entity_link(msg, state))

        expected_ids = {"email": "a@b.com", "telegram_user_id": "99", "slack_id": "abc"}
        mock_db.update_entity.assert_called_once_with("e-1", external_ids=expected_ids)


# ===================================================================
#  cmd_entity_note
# ===================================================================

class TestCmdEntityNote:

    @patch("telegram_bot.handlers.conversation_handlers._memory")
    def test_cmd_entity_note_stores(self, mock_memory):
        from telegram_bot.handlers.conversation_handlers import cmd_entity_note

        mock_memory.find_entity.return_value = {
            "id": "e-1", "name": "Alice", "external_ids": {},
        }
        mock_memory.remember.return_value = "new-id"

        msg = _make_message("/entity_note Alice She prefers email contact")
        state = _make_state()
        asyncio.run(cmd_entity_note(msg, state))

        mock_memory.find_entity.assert_called_once_with(query="Alice")
        mock_memory.remember.assert_called_once_with(
            "She prefers email contact", "general",
            source="admin_teach", entity_id="e-1",
        )
        msg.answer.assert_awaited_once()
        assert "Alice" in msg.answer.call_args[0][0]

    @patch("telegram_bot.handlers.conversation_handlers._memory")
    def test_cmd_entity_note_entity_not_found(self, mock_memory):
        from telegram_bot.handlers.conversation_handlers import cmd_entity_note

        mock_memory.find_entity.return_value = None

        msg = _make_message("/entity_note Unknown Some note")
        state = _make_state()
        asyncio.run(cmd_entity_note(msg, state))

        msg.answer.assert_awaited_once()
        assert "не найден" in msg.answer.call_args[0][0].lower()

    def test_cmd_entity_note_no_args_shows_usage(self):
        from telegram_bot.handlers.conversation_handlers import cmd_entity_note

        msg = _make_message("/entity_note")
        state = _make_state()
        asyncio.run(cmd_entity_note(msg, state))

        msg.answer.assert_awaited_once()
        assert "entity_note" in msg.answer.call_args[0][0].lower()

    def test_cmd_entity_note_missing_text_shows_usage(self):
        from telegram_bot.handlers.conversation_handlers import cmd_entity_note

        msg = _make_message("/entity_note Alice")
        state = _make_state()
        asyncio.run(cmd_entity_note(msg, state))

        msg.answer.assert_awaited_once()
        assert "entity_note" in msg.answer.call_args[0][0].lower()


# ===================================================================
#  cmd_teach
# ===================================================================

class TestCmdTeach:

    def test_no_args_shows_usage(self):
        from telegram_bot.handlers.conversation_handlers import cmd_teach

        msg = _make_message("/teach")
        state = _make_state()
        asyncio.run(cmd_teach(msg, state))

        msg.answer.assert_awaited_once()
        assert "/teach" in msg.answer.call_args[0][0]

    def test_whitespace_only_shows_usage(self):
        from telegram_bot.handlers.conversation_handlers import cmd_teach

        msg = _make_message("/teach   ")
        state = _make_state()
        asyncio.run(cmd_teach(msg, state))

        msg.answer.assert_awaited_once()
        assert "/teach" in msg.answer.call_args[0][0]

    @patch("telegram_bot.handlers.conversation_handlers._memory")
    @patch("telegram_bot.handlers.conversation_handlers._classify_teaching_text", new_callable=AsyncMock)
    def test_stores_classified_teaching(self, mock_classify, mock_memory):
        from telegram_bot.handlers.conversation_handlers import cmd_teach

        mock_classify.return_value = ("tech_support", "core")

        msg = _make_message("/teach some important knowledge")
        state = _make_state()
        asyncio.run(cmd_teach(msg, state))

        mock_classify.assert_awaited_once_with("some important knowledge")
        mock_memory.teach.assert_called_once_with(
            "some important knowledge", "tech_support", "core",
        )
        msg.answer.assert_awaited_once()
        text = msg.answer.call_args[0][0]
        assert "tech_support" in text
        assert "core" in text

    @patch("telegram_bot.handlers.conversation_handlers._memory")
    @patch("telegram_bot.handlers.conversation_handlers._classify_teaching_text", new_callable=AsyncMock)
    def test_exception_shows_error(self, mock_classify, mock_memory):
        from telegram_bot.handlers.conversation_handlers import cmd_teach

        mock_classify.side_effect = Exception("LLM down")

        msg = _make_message("/teach some text")
        state = _make_state()
        asyncio.run(cmd_teach(msg, state))

        msg.answer.assert_awaited_once()
        assert "не удалось сохранить" in msg.answer.call_args[0][0].lower()


# ===================================================================
#  cmd_knowledge
# ===================================================================

class TestCmdKnowledge:

    @patch("telegram_bot.handlers.conversation_handlers._memory")
    def test_empty_entries(self, mock_memory):
        from telegram_bot.handlers.conversation_handlers import cmd_knowledge

        mock_memory.list_knowledge.return_value = []

        msg = _make_message("/knowledge")
        state = _make_state()
        asyncio.run(cmd_knowledge(msg, state))

        msg.answer.assert_awaited_once()
        assert "не найдено" in msg.answer.call_args[0][0].lower()

    @patch("telegram_bot.handlers.conversation_handlers._send", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers._memory")
    def test_lists_entries(self, mock_memory, mock_send):
        from telegram_bot.handlers.conversation_handlers import cmd_knowledge
        from datetime import datetime

        mock_memory.list_knowledge.return_value = [
            {
                "id": "id-1", "title": "Title One", "tier": "core",
                "domain": "general", "source": "admin_teach",
                "content": "Short content", "created_at": datetime(2025, 1, 15),
            },
            {
                "id": "id-2", "title": "Title Two", "tier": "core",
                "domain": "general", "source": "extraction",
                "content": "Another", "created_at": datetime(2025, 2, 10),
            },
        ]

        msg = _make_message("/knowledge")
        state = _make_state()
        asyncio.run(cmd_knowledge(msg, state))

        mock_memory.list_knowledge.assert_called_once_with(domain=None, tier=None)
        mock_send.assert_awaited_once()
        text = mock_send.call_args[0][1]
        assert "2" in text  # count
        assert "Title One" in text
        assert "Title Two" in text
        assert "[core] general" in text

    @patch("telegram_bot.handlers.conversation_handlers._send", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers._memory")
    def test_verbose_flag(self, mock_memory, mock_send):
        from telegram_bot.handlers.conversation_handlers import cmd_knowledge
        from datetime import datetime

        mock_memory.list_knowledge.return_value = [
            {
                "id": "id-1", "title": "Title One", "tier": "core",
                "domain": "general", "source": "admin_teach",
                "content": "Verbose content here", "created_at": datetime(2025, 1, 15),
            },
        ]

        msg = _make_message("/knowledge -v")
        state = _make_state()
        asyncio.run(cmd_knowledge(msg, state))

        mock_send.assert_awaited_once()
        text = mock_send.call_args[0][1]
        # Verbose template includes ID, source, date, and <pre> content
        assert "ID: id-1" in text
        assert "Источник:" in text
        assert "<pre>" in text
        assert "Verbose content here" in text

    @patch("telegram_bot.handlers.conversation_handlers._send", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers._memory")
    def test_domain_filter(self, mock_memory, mock_send):
        from telegram_bot.handlers.conversation_handlers import cmd_knowledge
        from datetime import datetime

        mock_memory.list_knowledge.return_value = [
            {
                "id": "id-1", "title": "Title", "tier": "core",
                "domain": "tech_support", "source": "admin_teach",
                "content": "content", "created_at": datetime(2025, 1, 1),
            },
        ]

        msg = _make_message("/knowledge tech_support")
        state = _make_state()
        asyncio.run(cmd_knowledge(msg, state))

        mock_memory.list_knowledge.assert_called_once_with(
            domain="tech_support", tier=None,
        )

    @patch("telegram_bot.handlers.conversation_handlers._send", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers._memory")
    def test_domain_and_tier_filter(self, mock_memory, mock_send):
        from telegram_bot.handlers.conversation_handlers import cmd_knowledge
        from datetime import datetime

        mock_memory.list_knowledge.return_value = [
            {
                "id": "id-1", "title": "Title", "tier": "core",
                "domain": "tech_support", "source": "admin_teach",
                "content": "content", "created_at": datetime(2025, 1, 1),
            },
        ]

        msg = _make_message("/knowledge tech_support core")
        state = _make_state()
        asyncio.run(cmd_knowledge(msg, state))

        mock_memory.list_knowledge.assert_called_once_with(
            domain="tech_support", tier="core",
        )

    @patch("telegram_bot.handlers.conversation_handlers._memory")
    def test_exception_shows_error(self, mock_memory):
        from telegram_bot.handlers.conversation_handlers import cmd_knowledge

        mock_memory.list_knowledge.side_effect = Exception("DB down")

        msg = _make_message("/knowledge")
        state = _make_state()
        asyncio.run(cmd_knowledge(msg, state))

        msg.answer.assert_awaited_once()
        assert "ошибка" in msg.answer.call_args[0][0].lower()

    @patch("telegram_bot.handlers.conversation_handlers._send", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers._memory")
    def test_long_content_truncated(self, mock_memory, mock_send):
        from telegram_bot.handlers.conversation_handlers import cmd_knowledge
        from datetime import datetime

        long_content = "A" * 200
        mock_memory.list_knowledge.return_value = [
            {
                "id": "id-1", "title": "Title", "tier": "core",
                "domain": "general", "source": "admin_teach",
                "content": long_content, "created_at": datetime(2025, 1, 1),
            },
        ]

        # Verbose mode includes content in output, where truncation is visible
        msg = _make_message("/knowledge -v")
        state = _make_state()
        asyncio.run(cmd_knowledge(msg, state))

        mock_send.assert_awaited_once()
        text = mock_send.call_args[0][1]
        # Content should be truncated to 120 chars + "…"
        assert "A" * 120 + "…" in text
        assert "A" * 121 not in text.replace("…", "")


# ===================================================================
#  cmd_ksearch
# ===================================================================

class TestCmdKsearch:

    def test_no_args_shows_usage(self):
        from telegram_bot.handlers.conversation_handlers import cmd_ksearch

        msg = _make_message("/ksearch")
        state = _make_state()
        asyncio.run(cmd_ksearch(msg, state))

        msg.answer.assert_awaited_once()
        assert "/ksearch" in msg.answer.call_args[0][0]

    @patch("telegram_bot.handlers.conversation_handlers._send", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers._memory")
    def test_returns_results(self, mock_memory, mock_send):
        from telegram_bot.handlers.conversation_handlers import cmd_ksearch

        mock_memory.recall.return_value = [
            {
                "id": "id-1", "title": "Result One",
                "tier": "core", "domain": "general",
                "similarity": 0.85,
            },
            {
                "id": "id-2", "title": "Result Two",
                "tier": "supplementary", "domain": "tech_support",
                "similarity": 0.72,
            },
        ]

        msg = _make_message("/ksearch how to reset password")
        state = _make_state()
        asyncio.run(cmd_ksearch(msg, state))

        mock_memory.recall.assert_called_once_with(
            "how to reset password", limit=10,
        )
        mock_send.assert_awaited_once()
        text = mock_send.call_args[0][1]
        assert "how to reset password" in text
        assert "2" in text  # count
        assert "Result One" in text
        assert "Result Two" in text
        assert "0.85" in text
        assert "0.72" in text

    @patch("telegram_bot.handlers.conversation_handlers._memory")
    def test_no_results(self, mock_memory):
        from telegram_bot.handlers.conversation_handlers import cmd_ksearch

        mock_memory.recall.return_value = []

        msg = _make_message("/ksearch obscure query")
        state = _make_state()
        asyncio.run(cmd_ksearch(msg, state))

        msg.answer.assert_awaited_once()
        assert "не найдено" in msg.answer.call_args[0][0].lower()

    @patch("telegram_bot.handlers.conversation_handlers._memory")
    def test_exception_shows_error(self, mock_memory):
        from telegram_bot.handlers.conversation_handlers import cmd_ksearch

        mock_memory.recall.side_effect = Exception("Search failed")

        msg = _make_message("/ksearch some query")
        state = _make_state()
        asyncio.run(cmd_ksearch(msg, state))

        msg.answer.assert_awaited_once()
        assert "ошибка поиска" in msg.answer.call_args[0][0].lower()


# ===================================================================
#  cmd_forget
# ===================================================================

class TestCmdForget:

    def test_no_args_shows_usage(self):
        from telegram_bot.handlers.conversation_handlers import cmd_forget

        msg = _make_message("/forget")
        state = _make_state()
        asyncio.run(cmd_forget(msg, state))

        msg.answer.assert_awaited_once()
        assert "/forget" in msg.answer.call_args[0][0]

    @patch("telegram_bot.handlers.conversation_handlers._memory")
    def test_deactivates_entry(self, mock_memory):
        from telegram_bot.handlers.conversation_handlers import cmd_forget

        mock_memory.deactivate_entry.return_value = True

        msg = _make_message("/forget abc-123-def")
        state = _make_state()
        asyncio.run(cmd_forget(msg, state))

        mock_memory.deactivate_entry.assert_called_once_with("abc-123-def")
        msg.answer.assert_awaited_once()
        assert "удалена" in msg.answer.call_args[0][0].lower()

    @patch("telegram_bot.handlers.conversation_handlers._memory")
    def test_not_found(self, mock_memory):
        from telegram_bot.handlers.conversation_handlers import cmd_forget

        mock_memory.deactivate_entry.return_value = False

        msg = _make_message("/forget nonexistent-id")
        state = _make_state()
        asyncio.run(cmd_forget(msg, state))

        msg.answer.assert_awaited_once()
        assert "не найдена" in msg.answer.call_args[0][0].lower()

    @patch("telegram_bot.handlers.conversation_handlers._memory")
    def test_exception_shows_not_found(self, mock_memory):
        from telegram_bot.handlers.conversation_handlers import cmd_forget

        mock_memory.deactivate_entry.side_effect = Exception("DB error")

        msg = _make_message("/forget some-id")
        state = _make_state()
        asyncio.run(cmd_forget(msg, state))

        msg.answer.assert_awaited_once()
        assert "не найдена" in msg.answer.call_args[0][0].lower()


# ===================================================================
#  cmd_kedit
# ===================================================================

class TestCmdKedit:

    def test_no_args_shows_usage(self):
        from telegram_bot.handlers.conversation_handlers import cmd_kedit

        msg = _make_message("/kedit")
        state = _make_state()
        asyncio.run(cmd_kedit(msg, state))

        msg.answer.assert_awaited_once()
        assert "/kedit" in msg.answer.call_args[0][0]

    @patch("telegram_bot.handlers.conversation_handlers._kedit_pending", {})
    @patch("telegram_bot.handlers.conversation_handlers._send_html", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.conversation_handlers._memory")
    def test_shows_entry_for_editing(self, mock_memory, mock_send_html):
        from telegram_bot.handlers.conversation_handlers import cmd_kedit, _kedit_pending

        mock_memory.get_entry.return_value = {
            "id": "entry-123",
            "tier": "core",
            "domain": "general",
            "title": "Important fact",
            "content": "The actual content here",
        }
        sent_msg = MagicMock()
        sent_msg.message_id = 55
        mock_send_html.return_value = sent_msg

        msg = _make_message("/kedit entry-123", chat_id=100)
        state = _make_state()
        asyncio.run(cmd_kedit(msg, state))

        mock_memory.get_entry.assert_called_once_with("entry-123")
        mock_send_html.assert_awaited_once()
        text = mock_send_html.call_args[0][1]
        assert "Important fact" in text
        assert "The actual content here" in text
        assert "Ответьте на это сообщение" in text
        # Check that entry is stored in _kedit_pending
        assert _kedit_pending[(100, 55)] == "entry-123"

    @patch("telegram_bot.handlers.conversation_handlers._memory")
    def test_not_found(self, mock_memory):
        from telegram_bot.handlers.conversation_handlers import cmd_kedit

        mock_memory.get_entry.return_value = None

        msg = _make_message("/kedit nonexistent-id")
        state = _make_state()
        asyncio.run(cmd_kedit(msg, state))

        msg.answer.assert_awaited_once()
        assert "не найдена" in msg.answer.call_args[0][0].lower()

    @patch("telegram_bot.handlers.conversation_handlers._memory")
    def test_exception_shows_not_found(self, mock_memory):
        from telegram_bot.handlers.conversation_handlers import cmd_kedit

        mock_memory.get_entry.side_effect = Exception("DB error")

        msg = _make_message("/kedit some-id")
        state = _make_state()
        asyncio.run(cmd_kedit(msg, state))

        msg.answer.assert_awaited_once()
        assert "не найдена" in msg.answer.call_args[0][0].lower()


# ===================================================================
#  handle_kedit_reply
# ===================================================================

class TestHandleKeditReply:

    def test_no_reply_returns_false(self):
        from telegram_bot.handlers.conversation_handlers import handle_kedit_reply

        msg = _make_message("new content")
        msg.reply_to_message = None

        result = asyncio.run(handle_kedit_reply(msg))
        assert result is False

    def test_not_from_bot_returns_false(self):
        from telegram_bot.handlers.conversation_handlers import handle_kedit_reply

        msg = _make_message("new content")
        msg.reply_to_message = MagicMock()
        msg.reply_to_message.from_user = MagicMock()
        msg.reply_to_message.from_user.is_bot = False

        result = asyncio.run(handle_kedit_reply(msg))
        assert result is False

    @patch("telegram_bot.handlers.conversation_handlers._kedit_pending", {})
    def test_no_pending_returns_false(self):
        from telegram_bot.handlers.conversation_handlers import handle_kedit_reply

        msg = _make_message("new content", chat_id=100)
        msg.reply_to_message = MagicMock()
        msg.reply_to_message.from_user = MagicMock()
        msg.reply_to_message.from_user.is_bot = True
        msg.reply_to_message.message_id = 999

        result = asyncio.run(handle_kedit_reply(msg))
        assert result is False

    @patch("telegram_bot.handlers.conversation_handlers._memory")
    @patch("telegram_bot.handlers.conversation_handlers._kedit_pending",
           {(100, 55): "entry-123"})
    def test_updates_entry(self, mock_memory):
        from telegram_bot.handlers.conversation_handlers import handle_kedit_reply, _kedit_pending

        mock_memory.update_entry.return_value = True

        msg = _make_message("Updated content here", chat_id=100)
        msg.reply_to_message = MagicMock()
        msg.reply_to_message.from_user = MagicMock()
        msg.reply_to_message.from_user.is_bot = True
        msg.reply_to_message.message_id = 55

        result = asyncio.run(handle_kedit_reply(msg))

        assert result is True
        mock_memory.update_entry.assert_called_once_with("entry-123", "Updated content here")
        msg.answer.assert_awaited_once()
        assert "обновлена" in msg.answer.call_args[0][0].lower()
        # Pending should be cleaned up
        assert (100, 55) not in _kedit_pending

    @patch("telegram_bot.handlers.conversation_handlers._memory")
    @patch("telegram_bot.handlers.conversation_handlers._kedit_pending",
           {(100, 55): "entry-123"})
    def test_update_not_found(self, mock_memory):
        from telegram_bot.handlers.conversation_handlers import handle_kedit_reply

        mock_memory.update_entry.return_value = False

        msg = _make_message("Updated content", chat_id=100)
        msg.reply_to_message = MagicMock()
        msg.reply_to_message.from_user = MagicMock()
        msg.reply_to_message.from_user.is_bot = True
        msg.reply_to_message.message_id = 55

        result = asyncio.run(handle_kedit_reply(msg))

        assert result is True
        msg.answer.assert_awaited_once()
        assert "не найдена" in msg.answer.call_args[0][0].lower()

    @patch("telegram_bot.handlers.conversation_handlers._kedit_pending",
           {(100, 55): "entry-123"})
    def test_empty_content_shows_usage(self):
        from telegram_bot.handlers.conversation_handlers import handle_kedit_reply

        msg = _make_message("", chat_id=100)
        msg.reply_to_message = MagicMock()
        msg.reply_to_message.from_user = MagicMock()
        msg.reply_to_message.from_user.is_bot = True
        msg.reply_to_message.message_id = 55

        result = asyncio.run(handle_kedit_reply(msg))

        assert result is True
        msg.answer.assert_awaited_once()
        assert "/kedit" in msg.answer.call_args[0][0]


# ===================================================================
#  resolve_environment (handler_utils)
# ===================================================================

class TestResolveEnvironment:

    @patch("telegram_bot.backend_client.get_environment", new_callable=AsyncMock, return_value=None)
    def test_unbound_returns_defaults(self, mock_get_env):
        from telegram_bot.handler_utils import resolve_environment

        result = asyncio.run(resolve_environment(chat_id=100))

        mock_get_env.assert_awaited_once_with(chat_id=100)
        assert result == ("", None)

    @patch("telegram_bot.backend_client.get_environment", new_callable=AsyncMock)
    def test_bound_returns_context(self, mock_get_env):
        from telegram_bot.handler_utils import resolve_environment

        mock_get_env.return_value = {
            "system_context": "You are an editorial bot.",
            "allowed_domains": ["editorial", "general"],
        }

        result = asyncio.run(resolve_environment(chat_id=200))

        assert result == ("You are an editorial bot.", ["editorial", "general"])

    @patch("telegram_bot.backend_client.get_environment", new_callable=AsyncMock)
    def test_no_domains(self, mock_get_env):
        from telegram_bot.handler_utils import resolve_environment

        mock_get_env.return_value = {
            "system_context": "Admin context",
        }

        result = asyncio.run(resolve_environment(chat_id=300))

        assert result == ("Admin context", None)


# ===================================================================
#  resolve_entity_context (handler_utils)
# ===================================================================

class TestResolveEntityContext:

    @patch("telegram_bot.backend_client.get_entity_context", new_callable=AsyncMock, return_value="")
    def test_entity_not_found(self, mock_get_ctx):
        from telegram_bot.handler_utils import resolve_entity_context

        result = asyncio.run(resolve_entity_context(user_id=42))

        mock_get_ctx.assert_awaited_once_with(42)
        assert result == ""

    @patch("telegram_bot.backend_client.get_entity_context", new_callable=AsyncMock,
           return_value="Alice is the editor-in-chief.")
    def test_entity_found_returns_context(self, mock_get_ctx):
        from telegram_bot.handler_utils import resolve_entity_context

        result = asyncio.run(resolve_entity_context(user_id=42))

        mock_get_ctx.assert_awaited_once_with(42)
        assert result == "Alice is the editor-in-chief."

    @patch("telegram_bot.backend_client.get_entity_context", new_callable=AsyncMock, return_value="")
    def test_passes_correct_external_key(self, mock_get_ctx):
        from telegram_bot.handler_utils import resolve_entity_context

        asyncio.run(resolve_entity_context(user_id=999))

        mock_get_ctx.assert_awaited_once_with(999)
