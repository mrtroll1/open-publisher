"""Tests for Plan 2 handlers: group message handling, cmd_articles, cmd_lookup,
_answer_tech_question, _parse_with_llm, cmd_code, cmd_support, cmd_health.

All external dependencies (Gemini, DB, Telegram, Google Sheets, repo gateway)
are mocked — no real network calls.
"""

import asyncio
import json
from dataclasses import dataclass, field
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from common.models import (
    ArticleEntry,
    ContractorType,
    GlobalContractor,
    IPContractor,
    RoleCode,
    SamozanyatyContractor,
)


# ---------------------------------------------------------------------------
#  Contractor factories (reused from test_flow_callbacks_helpers)
# ---------------------------------------------------------------------------

def _global(**overrides) -> GlobalContractor:
    kwargs = dict(
        id="g1", name_en="Test Global", address="Addr", email="a@b.c",
        bank_name="Bank", bank_account="ACC", swift="SWIFT",
    )
    kwargs.update(overrides)
    return GlobalContractor(**kwargs)


def _samoz(**overrides) -> SamozanyatyContractor:
    kwargs = dict(
        id="s1", name_ru="Тест Самозанятый", address="Адрес", email="s@t.ru",
        bank_name="Банк", bank_account="12345", bik="044525225",
        corr_account="30101810400000000225",
        passport_series="1234", passport_number="567890", inn="123456789012",
    )
    kwargs.update(overrides)
    return SamozanyatyContractor(**kwargs)


def _ip(**overrides) -> IPContractor:
    kwargs = dict(
        id="ip1", name_ru="Тест ИП", email="ip@test.ru",
        bank_name="Банк", bank_account="12345", bik="044525225",
        corr_account="30101810400000000225",
        passport_series="1234", passport_number="567890",
        passport_issued_by="УФМС", passport_issued_date="01.01.2020",
        passport_code="123-456", ogrnip="123456789012345",
    )
    kwargs.update(overrides)
    return IPContractor(**kwargs)


# ---------------------------------------------------------------------------
#  Fake message / state / group config helpers
# ---------------------------------------------------------------------------

@dataclass
class FakeGroupChatConfig:
    chat_id: int = -100123
    allowed_commands: list = field(default_factory=lambda: ["health", "support", "articles", "lookup"])
    natural_language: bool = True


def _make_message(text: str = "", chat_id: int = -100123, user_id: int = 42) -> MagicMock:
    msg = AsyncMock()
    msg.text = text
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.reply_to_message = None
    msg.answer = AsyncMock()
    return msg


def _make_state() -> MagicMock:
    return AsyncMock()


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
#  handle_group_message — explicit /command dispatch
# ===================================================================

class TestHandleGroupMessageExplicitCommands:

    @patch("telegram_bot.flow_callbacks.run_healthchecks")
    @patch("telegram_bot.flow_callbacks.format_healthcheck_results")
    @patch("telegram_bot.flow_callbacks.bot")
    def test_explicit_health_command(self, mock_bot, mock_format, mock_run):
        from telegram_bot.flow_callbacks import handle_group_message
        mock_run.return_value = []
        mock_format.return_value = "All OK"
        mock_bot.send_chat_action = AsyncMock()

        msg = _make_message("/health")
        state = _make_state()
        config = FakeGroupChatConfig()

        asyncio.run(handle_group_message(msg, state, config))

        mock_run.assert_called_once()
        mock_format.assert_called_once()
        msg.answer.assert_awaited_once_with("All OK")

    @patch("telegram_bot.flow_callbacks.run_healthchecks")
    @patch("telegram_bot.flow_callbacks.format_healthcheck_results")
    @patch("telegram_bot.flow_callbacks.bot")
    def test_explicit_command_with_bot_suffix(self, mock_bot, mock_format, mock_run):
        from telegram_bot.flow_callbacks import handle_group_message
        mock_run.return_value = []
        mock_format.return_value = "OK"
        mock_bot.send_chat_action = AsyncMock()

        msg = _make_message("/health@republic_bot")
        state = _make_state()
        config = FakeGroupChatConfig()

        asyncio.run(handle_group_message(msg, state, config))

        mock_run.assert_called_once()

    def test_explicit_command_not_in_allowed_list(self):
        from telegram_bot.flow_callbacks import handle_group_message

        msg = _make_message("/health")
        state = _make_state()
        config = FakeGroupChatConfig(allowed_commands=["code"])

        asyncio.run(handle_group_message(msg, state, config))

        msg.answer.assert_not_awaited()

    def test_explicit_unknown_command_ignored(self):
        from telegram_bot.flow_callbacks import handle_group_message

        msg = _make_message("/unknown_cmd")
        state = _make_state()
        config = FakeGroupChatConfig(allowed_commands=["unknown_cmd"])

        # _dispatch_group_command returns early if handler not found
        asyncio.run(handle_group_message(msg, state, config))
        msg.answer.assert_not_awaited()

    @patch("telegram_bot.flow_callbacks.run_healthchecks")
    @patch("telegram_bot.flow_callbacks.format_healthcheck_results")
    @patch("telegram_bot.flow_callbacks.bot")
    def test_explicit_command_with_args(self, mock_bot, mock_format, mock_run):
        from telegram_bot.flow_callbacks import handle_group_message
        mock_run.return_value = []
        mock_format.return_value = "OK"
        mock_bot.send_chat_action = AsyncMock()

        msg = _make_message("/health extra_arg")
        state = _make_state()
        config = FakeGroupChatConfig()

        asyncio.run(handle_group_message(msg, state, config))

        mock_run.assert_called_once()


# ===================================================================
#  handle_group_message — natural language classification
# ===================================================================

class TestHandleGroupMessageNaturalLanguage:

    @patch("telegram_bot.flow_callbacks.BOT_USERNAME", "republic_bot")
    @patch("telegram_bot.flow_callbacks.CommandClassifier")
    @patch("telegram_bot.flow_callbacks.GeminiGateway")
    @patch("telegram_bot.flow_callbacks.run_healthchecks")
    @patch("telegram_bot.flow_callbacks.format_healthcheck_results")
    @patch("telegram_bot.flow_callbacks.bot")
    def test_mention_triggers_classification(
        self, mock_bot, mock_format, mock_run, MockGemini, MockClassifier,
    ):
        from telegram_bot.flow_callbacks import handle_group_message
        from backend.domain.services.command_classifier import ClassifiedCommand, ClassificationResult

        mock_instance = MagicMock()
        mock_instance.classify.return_value = ClassificationResult(
            classified=ClassifiedCommand(command="health", args=""), reply="",
        )
        MockClassifier.return_value = mock_instance
        mock_run.return_value = []
        mock_format.return_value = "All OK"
        mock_bot.send_chat_action = AsyncMock()

        msg = _make_message("@republic_bot проверь сайт")
        state = _make_state()
        config = FakeGroupChatConfig()

        asyncio.run(handle_group_message(msg, state, config))

        mock_instance.classify.assert_called_once()
        msg.answer.assert_awaited_once_with("All OK")

    @patch("telegram_bot.flow_callbacks.BOT_USERNAME", "republic_bot")
    def test_nl_disabled_ignores_mention(self):
        from telegram_bot.flow_callbacks import handle_group_message

        msg = _make_message("@republic_bot проверь сайт")
        state = _make_state()
        config = FakeGroupChatConfig(natural_language=False)

        asyncio.run(handle_group_message(msg, state, config))

        msg.answer.assert_not_awaited()

    @patch("telegram_bot.flow_callbacks.BOT_USERNAME", "republic_bot")
    def test_no_mention_no_reply_ignored(self):
        from telegram_bot.flow_callbacks import handle_group_message

        msg = _make_message("просто текст без упоминания")
        state = _make_state()
        config = FakeGroupChatConfig()

        asyncio.run(handle_group_message(msg, state, config))

        msg.answer.assert_not_awaited()

    @patch("telegram_bot.flow_callbacks.resolve_entity_context", return_value="")
    @patch("telegram_bot.flow_callbacks.resolve_environment", return_value=("", None))
    @patch("telegram_bot.flow_callbacks.ThinkingMessage")
    @patch("telegram_bot.flow_callbacks.BOT_USERNAME", "republic_bot")
    @patch("telegram_bot.flow_callbacks.CommandClassifier")
    @patch("telegram_bot.flow_callbacks.GeminiGateway")
    def test_classification_returns_none_no_dispatch(
        self, MockGemini, MockClassifier, MockThinking,
        mock_resolve_env, mock_resolve_entity,
    ):
        from telegram_bot.flow_callbacks import handle_group_message
        from backend.domain.services.command_classifier import ClassificationResult
        from backend.domain.services.conversation_service import generate_nl_reply

        mock_tm = _mock_thinking_message_class()
        MockThinking.side_effect = mock_tm

        mock_instance = MagicMock()
        mock_instance.classify.return_value = ClassificationResult(classified=None, reply="")
        MockClassifier.return_value = mock_instance

        msg = _make_message("@republic_bot что нового?")
        state = _make_state()
        config = FakeGroupChatConfig()

        asyncio.run(handle_group_message(msg, state, config))

        # ThinkingMessage is used for the RAG reply path
        mock_tm._instance.finish_long.assert_awaited_once()

    @patch("telegram_bot.flow_callbacks.BOT_USERNAME", "republic_bot")
    @patch("telegram_bot.flow_callbacks.CommandClassifier")
    @patch("telegram_bot.flow_callbacks.GeminiGateway")
    def test_classification_error_silenced(self, MockGemini, MockClassifier):
        from telegram_bot.flow_callbacks import handle_group_message

        mock_instance = MagicMock()
        mock_instance.classify.side_effect = RuntimeError("Gemini down")
        MockClassifier.return_value = mock_instance

        msg = _make_message("@republic_bot проверь сайт")
        state = _make_state()
        config = FakeGroupChatConfig()

        asyncio.run(handle_group_message(msg, state, config))

        msg.answer.assert_not_awaited()

    @patch("telegram_bot.flow_callbacks.BOT_USERNAME", "republic_bot")
    @patch("telegram_bot.flow_callbacks.CommandClassifier")
    @patch("telegram_bot.flow_callbacks.GeminiGateway")
    def test_empty_allowed_commands_no_classification(self, MockGemini, MockClassifier):
        from telegram_bot.flow_callbacks import handle_group_message

        msg = _make_message("@republic_bot проверь сайт")
        state = _make_state()
        config = FakeGroupChatConfig(allowed_commands=[])

        asyncio.run(handle_group_message(msg, state, config))

        MockClassifier.return_value.classify.assert_not_called()

    @patch("telegram_bot.flow_callbacks.BOT_USERNAME", "republic_bot")
    @patch("telegram_bot.flow_callbacks.CommandClassifier")
    @patch("telegram_bot.flow_callbacks.GeminiGateway")
    @patch("telegram_bot.flow_callbacks.run_healthchecks")
    @patch("telegram_bot.flow_callbacks.format_healthcheck_results")
    @patch("telegram_bot.flow_callbacks.bot")
    def test_reply_to_bot_triggers_classification(
        self, mock_bot, mock_format, mock_run, MockGemini, MockClassifier,
    ):
        from telegram_bot.flow_callbacks import handle_group_message
        from backend.domain.services.command_classifier import ClassifiedCommand, ClassificationResult

        mock_instance = MagicMock()
        mock_instance.classify.return_value = ClassificationResult(
            classified=ClassifiedCommand(command="health", args=""), reply="",
        )
        MockClassifier.return_value = mock_instance
        mock_run.return_value = []
        mock_format.return_value = "OK"
        mock_bot.send_chat_action = AsyncMock()

        msg = _make_message("проверь сайт")
        msg.reply_to_message = MagicMock()
        msg.reply_to_message.from_user = MagicMock()
        msg.reply_to_message.from_user.is_bot = True
        state = _make_state()
        config = FakeGroupChatConfig()

        asyncio.run(handle_group_message(msg, state, config))

        mock_instance.classify.assert_called_once()
        msg.answer.assert_awaited_once()

    def test_empty_text_no_crash(self):
        from telegram_bot.flow_callbacks import handle_group_message

        msg = _make_message("")
        msg.text = None
        state = _make_state()
        config = FakeGroupChatConfig()

        asyncio.run(handle_group_message(msg, state, config))

        msg.answer.assert_not_awaited()


# ===================================================================
#  cmd_health
# ===================================================================

class TestCmdHealth:

    @patch("telegram_bot.flow_callbacks.run_healthchecks")
    @patch("telegram_bot.flow_callbacks.format_healthcheck_results")
    @patch("telegram_bot.flow_callbacks.bot")
    def test_calls_healthcheck_and_replies(self, mock_bot, mock_format, mock_run):
        from telegram_bot.flow_callbacks import cmd_health

        mock_run.return_value = [MagicMock()]
        mock_format.return_value = "site.com — ok"
        mock_bot.send_chat_action = AsyncMock()

        msg = _make_message("/health")
        state = _make_state()

        asyncio.run(cmd_health(msg, state))

        mock_run.assert_called_once()
        mock_format.assert_called_once_with(mock_run.return_value)
        msg.answer.assert_awaited_once_with("site.com — ok")

    @patch("telegram_bot.flow_callbacks.run_healthchecks")
    @patch("telegram_bot.flow_callbacks.format_healthcheck_results")
    @patch("telegram_bot.flow_callbacks.bot")
    def test_empty_results(self, mock_bot, mock_format, mock_run):
        from telegram_bot.flow_callbacks import cmd_health

        mock_run.return_value = []
        mock_format.return_value = "No checks configured."
        mock_bot.send_chat_action = AsyncMock()

        msg = _make_message("/health")
        state = _make_state()

        asyncio.run(cmd_health(msg, state))

        msg.answer.assert_awaited_once_with("No checks configured.")


# ===================================================================
#  cmd_support
# ===================================================================

class TestCmdSupport:

    @patch("telegram_bot.flow_callbacks.ThinkingMessage")
    @patch("telegram_bot.flow_callbacks._answer_tech_question")
    @patch("telegram_bot.flow_callbacks.bot")
    def test_valid_question(self, mock_bot, mock_answer, MockThinking):
        from telegram_bot.flow_callbacks import cmd_support

        mock_answer.return_value = "Ответ на вопрос"
        mock_bot.send_chat_action = AsyncMock()
        mock_tm = _mock_thinking_message_class()
        MockThinking.side_effect = mock_tm

        msg = _make_message("/support как работает подписка?")
        state = _make_state()

        asyncio.run(cmd_support(msg, state))

        mock_answer.assert_called_once_with("как работает подписка?", False, False, on_event=ANY)
        mock_tm._instance.finish_long.assert_awaited_once()
        assert "Ответ на вопрос" in mock_tm._instance.finish_long.call_args[0][0]

    def test_no_question_shows_usage(self):
        from telegram_bot.flow_callbacks import cmd_support

        msg = _make_message("/support")
        state = _make_state()

        asyncio.run(cmd_support(msg, state))

        msg.answer.assert_awaited_once()
        assert "Использование" in msg.answer.call_args[0][0]

    def test_empty_question_shows_usage(self):
        from telegram_bot.flow_callbacks import cmd_support

        msg = _make_message("/support   ")
        state = _make_state()

        asyncio.run(cmd_support(msg, state))

        msg.answer.assert_awaited_once()
        assert "Использование" in msg.answer.call_args[0][0]

    @patch("telegram_bot.flow_callbacks._answer_tech_question")
    @patch("telegram_bot.flow_callbacks.bot")
    def test_verbose_flag(self, mock_bot, mock_answer):
        from telegram_bot.flow_callbacks import cmd_support

        mock_answer.return_value = "Verbose answer"
        mock_bot.send_chat_action = AsyncMock()

        msg = _make_message("/support -v как настроить?")
        state = _make_state()

        asyncio.run(cmd_support(msg, state))

        mock_answer.assert_called_once_with("как настроить?", True, False, on_event=ANY)

    @patch("telegram_bot.flow_callbacks._answer_tech_question")
    @patch("telegram_bot.flow_callbacks.bot")
    def test_verbose_word_flag(self, mock_bot, mock_answer):
        from telegram_bot.flow_callbacks import cmd_support

        mock_answer.return_value = "Verbose answer"
        mock_bot.send_chat_action = AsyncMock()

        msg = _make_message("/support verbose как настроить?")
        state = _make_state()

        asyncio.run(cmd_support(msg, state))

        mock_answer.assert_called_once_with("как настроить?", True, False, on_event=ANY)

    @patch("telegram_bot.flow_callbacks._answer_tech_question")
    @patch("telegram_bot.flow_callbacks.bot")
    def test_v_alone_treated_as_question(self, mock_bot, mock_answer):
        """'-v' without space is not a flag — it's treated as the question itself."""
        from telegram_bot.flow_callbacks import cmd_support

        mock_answer.return_value = "answer"
        mock_bot.send_chat_action = AsyncMock()

        msg = _make_message("/support -v")
        state = _make_state()

        asyncio.run(cmd_support(msg, state))

        mock_answer.assert_called_once_with("-v", False, False, on_event=ANY)

    @patch("telegram_bot.flow_callbacks._answer_tech_question")
    @patch("telegram_bot.flow_callbacks.bot")
    def test_v_with_trailing_space_treated_as_question(self, mock_bot, mock_answer):
        """'-v ' (with trailing space) is stripped to '-v' and treated as the question."""
        from telegram_bot.flow_callbacks import cmd_support

        mock_answer.return_value = "answer"
        mock_bot.send_chat_action = AsyncMock()

        msg = _make_message("/support -v ")
        state = _make_state()

        asyncio.run(cmd_support(msg, state))

        mock_answer.assert_called_once_with("-v", False, False, on_event=ANY)

    @patch("telegram_bot.flow_callbacks._answer_tech_question")
    @patch("telegram_bot.flow_callbacks.bot")
    def test_long_answer_not_truncated(self, mock_bot, mock_answer):
        from telegram_bot.flow_callbacks import cmd_support

        mock_answer.return_value = "x" * 5000
        mock_bot.send_chat_action = AsyncMock()

        msg = _make_message("/support вопрос")
        state = _make_state()

        asyncio.run(cmd_support(msg, state))

        # Long answers are split by _send_html, not truncated
        assert msg.answer.call_count >= 2

    @patch("telegram_bot.flow_callbacks._answer_tech_question")
    @patch("telegram_bot.flow_callbacks.bot")
    def test_exception_returns_error(self, mock_bot, mock_answer):
        from telegram_bot.flow_callbacks import cmd_support

        mock_answer.side_effect = RuntimeError("Gemini down")
        mock_bot.send_chat_action = AsyncMock()

        msg = _make_message("/support вопрос")
        state = _make_state()

        asyncio.run(cmd_support(msg, state))

        answer = msg.answer.call_args[0][0]
        assert "Не удалось" in answer


# ===================================================================
#  _answer_tech_question
# ===================================================================

class TestAnswerTechQuestion:

    @patch("telegram_bot.flow_callbacks.RepoGateway")
    @patch("telegram_bot.flow_callbacks.GeminiGateway")
    @patch("telegram_bot.flow_callbacks.compose_request")
    def test_basic_question_without_code_context(self, mock_compose, MockGemini, MockRepo):
        from telegram_bot.flow_callbacks import _answer_tech_question

        # tech_search_terms says no code needed
        mock_compose.tech_search_terms.return_value = ("prompt1", "model1", [])
        mock_compose.tech_support_question.return_value = ("prompt2", "model2", [])

        mock_gemini = MagicMock()
        mock_gemini.call.side_effect = [
            {"needs_code": False},
            {"answer": "Подписка работает так..."},
        ]
        MockGemini.return_value = mock_gemini

        result = _answer_tech_question("как работает подписка?", False, False)

        assert result == "Подписка работает так..."
        assert mock_gemini.call.call_count == 2
        # tech_support_question called with empty code_context
        mock_compose.tech_support_question.assert_called_once_with(
            "как работает подписка?", "", False,
        )

    @patch("telegram_bot.flow_callbacks.run_claude_code")
    @patch("telegram_bot.flow_callbacks.GeminiGateway")
    @patch("telegram_bot.flow_callbacks.compose_request")
    def test_question_needing_code_uses_claude(self, mock_compose, MockGemini, mock_run_claude):
        from telegram_bot.flow_callbacks import _answer_tech_question

        mock_compose.tech_search_terms.return_value = ("prompt1", "model1", [])

        mock_gemini = MagicMock()
        mock_gemini.call.return_value = {"needs_code": True}
        MockGemini.return_value = mock_gemini

        mock_run_claude.return_value = "Healthcheck uses requests.get"

        result = _answer_tech_question("what is healthcheck?", True, False)

        assert result == "Healthcheck uses requests.get"
        mock_run_claude.assert_called_once_with(
            "what is healthcheck?", verbose=True, expert=False, mode="explore", on_event=None,
        )

    @patch("telegram_bot.flow_callbacks.GeminiGateway")
    @patch("telegram_bot.flow_callbacks.compose_request")
    def test_triage_error_falls_back_to_gemini(self, mock_compose, MockGemini):
        from telegram_bot.flow_callbacks import _answer_tech_question

        mock_compose.tech_search_terms.side_effect = RuntimeError("Gemini down")
        mock_compose.tech_support_question.return_value = ("prompt2", "model2", [])

        mock_gemini = MagicMock()
        mock_gemini.call.return_value = {"answer": "answer without code"}
        MockGemini.return_value = mock_gemini

        result = _answer_tech_question("вопрос", False, False)

        assert result == "answer without code"
        mock_compose.tech_support_question.assert_called_once_with("вопрос", "", False)

    @patch("telegram_bot.flow_callbacks.RepoGateway")
    @patch("telegram_bot.flow_callbacks.GeminiGateway")
    @patch("telegram_bot.flow_callbacks.compose_request")
    def test_answer_falls_back_to_str(self, mock_compose, MockGemini, MockRepo):
        from telegram_bot.flow_callbacks import _answer_tech_question

        mock_compose.tech_search_terms.return_value = ("p", "m", [])
        mock_compose.tech_support_question.return_value = ("p", "m", [])

        mock_gemini = MagicMock()
        mock_gemini.call.side_effect = [
            {"needs_code": False},
            {"other_key": "value"},  # No "answer" key
        ]
        MockGemini.return_value = mock_gemini

        result = _answer_tech_question("test", False, False)

        # Falls back to str(result) when no "answer" key
        assert "other_key" in result

    @patch("telegram_bot.flow_callbacks.RepoGateway")
    @patch("telegram_bot.flow_callbacks.GeminiGateway")
    @patch("telegram_bot.flow_callbacks.compose_request")
    def test_verbose_passed_through(self, mock_compose, MockGemini, MockRepo):
        from telegram_bot.flow_callbacks import _answer_tech_question

        mock_compose.tech_search_terms.return_value = ("p", "m", [])
        mock_compose.tech_support_question.return_value = ("p", "m", [])

        mock_gemini = MagicMock()
        mock_gemini.call.side_effect = [
            {"needs_code": False},
            {"answer": "verbose answer"},
        ]
        MockGemini.return_value = mock_gemini

        _answer_tech_question("q", verbose=True, expert=False)

        mock_compose.tech_support_question.assert_called_once_with("q", "", True)

    @patch("telegram_bot.flow_callbacks.run_claude_code")
    @patch("telegram_bot.flow_callbacks.GeminiGateway")
    @patch("telegram_bot.flow_callbacks.compose_request")
    def test_needs_code_true_delegates_to_claude(self, mock_compose, MockGemini, mock_run_claude):
        from telegram_bot.flow_callbacks import _answer_tech_question

        mock_compose.tech_search_terms.return_value = ("p", "m", [])

        mock_gemini = MagicMock()
        mock_gemini.call.return_value = {"needs_code": True}
        MockGemini.return_value = mock_gemini

        mock_run_claude.return_value = "claude answer"

        result = _answer_tech_question("q", False, False)

        assert result == "claude answer"
        mock_run_claude.assert_called_once_with("q", verbose=False, expert=False, mode="explore", on_event=None)


# ===================================================================
#  cmd_code — task saving and rating buttons
# ===================================================================

class TestCmdCode:
    """cmd_code uses a LOCAL import of DbGateway, so we patch at the source module."""

    @patch("telegram_bot.flow_callbacks.ThinkingMessage")
    @patch("telegram_bot.flow_callbacks._db")
    @patch("telegram_bot.flow_callbacks.run_claude_code")
    @patch("telegram_bot.flow_callbacks.bot")
    def test_successful_run_with_db_save(self, mock_bot, mock_run, mock_db, MockThinking):
        from telegram_bot.flow_callbacks import cmd_code

        mock_run.return_value = "Code result"
        mock_db.create_code_task.return_value = "task-abc-123"
        mock_bot.send_chat_action = AsyncMock()
        mock_tm = _mock_thinking_message_class()
        MockThinking.side_effect = mock_tm

        msg = _make_message("/code check tests")
        state = _make_state()

        asyncio.run(cmd_code(msg, state))

        mock_run.assert_called_once_with("check tests", False, False, mode="changes", on_event=ANY)
        mock_db.create_code_task.assert_called_once()
        mock_tm._instance.finish_long.assert_awaited_once()
        call_kwargs = mock_tm._instance.finish_long.call_args
        assert call_kwargs[0][0] == "Code result"
        assert call_kwargs[1]["reply_markup"] is not None

    def test_no_args_shows_usage(self):
        from telegram_bot.flow_callbacks import cmd_code

        msg = _make_message("/code")
        state = _make_state()

        asyncio.run(cmd_code(msg, state))

        msg.answer.assert_awaited_once()
        assert "Использование" in msg.answer.call_args[0][0]

    def test_empty_args_shows_usage(self):
        from telegram_bot.flow_callbacks import cmd_code

        msg = _make_message("/code   ")
        state = _make_state()

        asyncio.run(cmd_code(msg, state))

        msg.answer.assert_awaited_once()
        assert "Использование" in msg.answer.call_args[0][0]

    @patch("telegram_bot.flow_callbacks._db")
    @patch("telegram_bot.flow_callbacks.run_claude_code")
    @patch("telegram_bot.flow_callbacks.bot")
    def test_verbose_flag(self, mock_bot, mock_run, mock_db):
        from telegram_bot.flow_callbacks import cmd_code

        mock_run.return_value = "Verbose result"
        mock_db.create_code_task.return_value = "t1"
        mock_bot.send_chat_action = AsyncMock()

        msg = _make_message("/code -v analyze this")
        state = _make_state()

        asyncio.run(cmd_code(msg, state))

        mock_run.assert_called_once_with("analyze this", True, False, mode="changes", on_event=ANY)

    @patch("telegram_bot.flow_callbacks._db")
    @patch("telegram_bot.flow_callbacks.run_claude_code")
    @patch("telegram_bot.flow_callbacks.bot")
    def test_verbose_word_flag(self, mock_bot, mock_run, mock_db):
        from telegram_bot.flow_callbacks import cmd_code

        mock_run.return_value = "Verbose result"
        mock_db.create_code_task.return_value = "t1"
        mock_bot.send_chat_action = AsyncMock()

        msg = _make_message("/code verbose analyze this")
        state = _make_state()

        asyncio.run(cmd_code(msg, state))

        mock_run.assert_called_once_with("analyze this", True, False, mode="changes", on_event=ANY)

    @patch("telegram_bot.flow_callbacks.run_claude_code")
    @patch("telegram_bot.flow_callbacks.bot")
    def test_v_alone_treated_as_prompt(self, mock_bot, mock_run):
        """'-v' without space is not a flag — it's treated as the prompt itself."""
        from telegram_bot.flow_callbacks import cmd_code

        mock_run.return_value = "result"
        mock_bot.send_chat_action = AsyncMock()

        msg = _make_message("/code -v")
        state = _make_state()

        asyncio.run(cmd_code(msg, state))

        mock_run.assert_called_once_with("-v", False, False, mode="changes", on_event=ANY)

    @patch("telegram_bot.flow_callbacks.run_claude_code")
    @patch("telegram_bot.flow_callbacks.bot")
    def test_v_with_trailing_space_treated_as_prompt(self, mock_bot, mock_run):
        """'-v ' (with trailing space) is stripped to '-v' and treated as the prompt."""
        from telegram_bot.flow_callbacks import cmd_code

        mock_run.return_value = "result"
        mock_bot.send_chat_action = AsyncMock()

        msg = _make_message("/code -v ")
        state = _make_state()

        asyncio.run(cmd_code(msg, state))

        mock_run.assert_called_once_with("-v", False, False, mode="changes", on_event=ANY)

    @patch("telegram_bot.flow_callbacks.ThinkingMessage")
    @patch("telegram_bot.flow_callbacks._db")
    @patch("telegram_bot.flow_callbacks.run_claude_code")
    @patch("telegram_bot.flow_callbacks.bot")
    def test_db_save_failure_still_sends_answer(self, mock_bot, mock_run, mock_db, MockThinking):
        from telegram_bot.flow_callbacks import cmd_code

        mock_run.return_value = "Code result"
        mock_db.create_code_task.side_effect = RuntimeError("DB down")
        mock_bot.send_chat_action = AsyncMock()
        mock_tm = _mock_thinking_message_class()
        MockThinking.side_effect = mock_tm

        msg = _make_message("/code test")
        state = _make_state()

        asyncio.run(cmd_code(msg, state))

        mock_tm._instance.finish_long.assert_awaited_once()
        assert mock_tm._instance.finish_long.call_args[0][0] == "Code result"
        # DB failed, so reply_markup should be None
        assert mock_tm._instance.finish_long.call_args[1]["reply_markup"] is None

    @patch("telegram_bot.flow_callbacks.run_claude_code")
    @patch("telegram_bot.flow_callbacks.bot")
    def test_code_execution_failure(self, mock_bot, mock_run):
        from telegram_bot.flow_callbacks import cmd_code

        mock_run.side_effect = RuntimeError("Claude CLI crashed")
        mock_bot.send_chat_action = AsyncMock()

        msg = _make_message("/code test")
        state = _make_state()

        asyncio.run(cmd_code(msg, state))

        answer = msg.answer.call_args[0][0]
        assert "Не удалось" in answer

    @patch("telegram_bot.flow_callbacks._db")
    @patch("telegram_bot.flow_callbacks.run_claude_code")
    @patch("telegram_bot.flow_callbacks.bot")
    def test_rating_keyboard_has_5_buttons(self, mock_bot, mock_run, mock_db):
        from telegram_bot.flow_callbacks import cmd_code

        mock_run.return_value = "Result"
        mock_db.create_code_task.return_value = "task-xyz"
        mock_bot.send_chat_action = AsyncMock()

        msg = _make_message("/code do something")
        state = _make_state()

        asyncio.run(cmd_code(msg, state))

        markup = msg.answer.call_args[1]["reply_markup"]
        assert markup is not None
        buttons = markup.inline_keyboard[0]
        assert len(buttons) == 5
        assert buttons[0].text == "1"
        assert buttons[4].text == "5"
        assert "task-xyz" in buttons[2].callback_data


# ===================================================================
#  cmd_articles
# ===================================================================

class TestCmdArticles:

    @patch("telegram_bot.flow_callbacks.fetch_articles")
    @patch("telegram_bot.flow_callbacks.get_contractors")
    @patch("telegram_bot.flow_callbacks.find_contractor")
    @patch("telegram_bot.flow_callbacks.bot")
    def test_articles_found(self, mock_bot, mock_find, mock_get, mock_fetch):
        from telegram_bot.flow_callbacks import cmd_articles

        contractor = _samoz(name_ru="Иван Иванов", role_code=RoleCode.AUTHOR)
        mock_get.return_value = [contractor]
        mock_find.return_value = contractor
        mock_fetch.return_value = [
            ArticleEntry(article_id="100"),
            ArticleEntry(article_id="200"),
        ]
        mock_bot.send_chat_action = AsyncMock()

        msg = _make_message("/articles Иванов")
        state = _make_state()

        asyncio.run(cmd_articles(msg, state))

        msg.answer.assert_awaited_once()
        text = msg.answer.call_args[0][0]
        assert "Иван Иванов" in text
        assert "100" in text
        assert "200" in text
        assert "Статей: 2" in text

    @patch("telegram_bot.flow_callbacks.fetch_articles")
    @patch("telegram_bot.flow_callbacks.get_contractors")
    @patch("telegram_bot.flow_callbacks.find_contractor")
    @patch("telegram_bot.flow_callbacks.bot")
    def test_articles_with_explicit_month(self, mock_bot, mock_find, mock_get, mock_fetch):
        from telegram_bot.flow_callbacks import cmd_articles

        contractor = _samoz(name_ru="Иван Иванов", role_code=RoleCode.AUTHOR)
        mock_get.return_value = [contractor]
        mock_find.return_value = contractor
        mock_fetch.return_value = [ArticleEntry(article_id="300")]
        mock_bot.send_chat_action = AsyncMock()

        msg = _make_message("/articles Иванов 2026-01")
        state = _make_state()

        asyncio.run(cmd_articles(msg, state))

        mock_fetch.assert_called_once_with(contractor, "2026-01")
        text = msg.answer.call_args[0][0]
        assert "2026-01" in text

    @patch("telegram_bot.flow_callbacks.get_contractors")
    @patch("telegram_bot.flow_callbacks.find_contractor")
    @patch("telegram_bot.flow_callbacks.fuzzy_find")
    def test_contractor_not_found_fuzzy_match(self, mock_fuzzy, mock_find, mock_get):
        from telegram_bot.flow_callbacks import cmd_articles

        contractor = _samoz(name_ru="Иван Иванов")
        mock_get.return_value = [contractor]
        mock_find.return_value = None
        mock_fuzzy.return_value = [(contractor, 0.6)]

        msg = _make_message("/articles Иваноф")
        state = _make_state()

        asyncio.run(cmd_articles(msg, state))

        msg.answer.assert_awaited_once()
        text = msg.answer.call_args[0][0]
        assert "Точного совпадения нет" in text
        assert "Иван Иванов" in text

    @patch("telegram_bot.flow_callbacks.get_contractors")
    @patch("telegram_bot.flow_callbacks.find_contractor")
    @patch("telegram_bot.flow_callbacks.fuzzy_find")
    def test_contractor_not_found_no_fuzzy(self, mock_fuzzy, mock_find, mock_get):
        from telegram_bot.flow_callbacks import cmd_articles

        mock_get.return_value = []
        mock_find.return_value = None
        mock_fuzzy.return_value = []

        msg = _make_message("/articles Несуществующий")
        state = _make_state()

        asyncio.run(cmd_articles(msg, state))

        msg.answer.assert_awaited_once()
        text = msg.answer.call_args[0][0]
        assert "не найден" in text

    def test_no_args_shows_usage(self):
        from telegram_bot.flow_callbacks import cmd_articles

        msg = _make_message("/articles")
        state = _make_state()

        asyncio.run(cmd_articles(msg, state))

        msg.answer.assert_awaited_once()
        assert "Использование" in msg.answer.call_args[0][0]

    @patch("telegram_bot.flow_callbacks.fetch_articles")
    @patch("telegram_bot.flow_callbacks.get_contractors")
    @patch("telegram_bot.flow_callbacks.find_contractor")
    @patch("telegram_bot.flow_callbacks.bot")
    def test_no_articles_for_month(self, mock_bot, mock_find, mock_get, mock_fetch):
        from telegram_bot.flow_callbacks import cmd_articles

        contractor = _samoz(name_ru="Иван Иванов")
        mock_get.return_value = [contractor]
        mock_find.return_value = contractor
        mock_fetch.return_value = []
        mock_bot.send_chat_action = AsyncMock()

        msg = _make_message("/articles Иванов 2026-01")
        state = _make_state()

        asyncio.run(cmd_articles(msg, state))

        msg.answer.assert_awaited_once()
        text = msg.answer.call_args[0][0]
        assert "нет публикаций" in text


# ===================================================================
#  cmd_lookup
# ===================================================================

class TestCmdLookup:

    @patch("telegram_bot.flow_callbacks.get_contractors")
    @patch("telegram_bot.flow_callbacks.find_contractor")
    def test_lookup_samozanyaty(self, mock_find, mock_get):
        from telegram_bot.flow_callbacks import cmd_lookup

        contractor = _samoz(
            name_ru="Иван Петров", email="ivan@test.ru",
            mags="republic", telegram="@ivan",
            role_code=RoleCode.AUTHOR, invoice_number=42,
        )
        mock_get.return_value = [contractor]
        mock_find.return_value = contractor

        msg = _make_message("/lookup Петров")
        state = _make_state()

        asyncio.run(cmd_lookup(msg, state))

        msg.answer.assert_awaited_once()
        text = msg.answer.call_args[0][0]
        assert "Иван Петров" in text
        assert "самозанятый" in text
        assert "автор" in text
        assert "republic" in text
        assert "ivan@test.ru" in text
        assert "привязан" in text
        assert "42" in text
        assert "заполнены" in text

    @patch("telegram_bot.flow_callbacks.get_contractors")
    @patch("telegram_bot.flow_callbacks.find_contractor")
    def test_lookup_hides_sensitive_data(self, mock_find, mock_get):
        from telegram_bot.flow_callbacks import cmd_lookup

        contractor = _samoz(
            passport_series="9876", passport_number="543210",
            inn="111222333444", bank_account="40817810000000000001",
            bik="044525225", corr_account="30101810400000000225",
            secret_code="SECRET123",
        )
        mock_get.return_value = [contractor]
        mock_find.return_value = contractor

        msg = _make_message("/lookup Тест")
        state = _make_state()

        asyncio.run(cmd_lookup(msg, state))

        text = msg.answer.call_args[0][0]
        assert "9876" not in text
        assert "543210" not in text
        assert "111222333444" not in text
        assert "40817810000000000001" not in text
        assert "SECRET123" not in text

    @patch("telegram_bot.flow_callbacks.get_contractors")
    @patch("telegram_bot.flow_callbacks.find_contractor")
    def test_lookup_no_telegram(self, mock_find, mock_get):
        from telegram_bot.flow_callbacks import cmd_lookup

        contractor = _global(telegram="")
        mock_get.return_value = [contractor]
        mock_find.return_value = contractor

        msg = _make_message("/lookup Test")
        state = _make_state()

        asyncio.run(cmd_lookup(msg, state))

        text = msg.answer.call_args[0][0]
        assert "не привязан" in text

    @patch("telegram_bot.flow_callbacks.get_contractors")
    @patch("telegram_bot.flow_callbacks.find_contractor")
    def test_lookup_no_bank_data(self, mock_find, mock_get):
        from telegram_bot.flow_callbacks import cmd_lookup

        contractor = _global(bank_name="", bank_account="")
        mock_get.return_value = [contractor]
        mock_find.return_value = contractor

        msg = _make_message("/lookup Test")
        state = _make_state()

        asyncio.run(cmd_lookup(msg, state))

        text = msg.answer.call_args[0][0]
        assert "не заполнены" in text

    @patch("telegram_bot.flow_callbacks.get_contractors")
    @patch("telegram_bot.flow_callbacks.find_contractor")
    @patch("telegram_bot.flow_callbacks.fuzzy_find")
    def test_lookup_not_found_fuzzy(self, mock_fuzzy, mock_find, mock_get):
        from telegram_bot.flow_callbacks import cmd_lookup

        contractor = _global(name_en="John Smith")
        mock_get.return_value = [contractor]
        mock_find.return_value = None
        mock_fuzzy.return_value = [(contractor, 0.5)]

        msg = _make_message("/lookup Smit")
        state = _make_state()

        asyncio.run(cmd_lookup(msg, state))

        text = msg.answer.call_args[0][0]
        assert "Точного совпадения нет" in text
        assert "John Smith" in text

    @patch("telegram_bot.flow_callbacks.get_contractors")
    @patch("telegram_bot.flow_callbacks.find_contractor")
    @patch("telegram_bot.flow_callbacks.fuzzy_find")
    def test_lookup_not_found_no_fuzzy(self, mock_fuzzy, mock_find, mock_get):
        from telegram_bot.flow_callbacks import cmd_lookup

        mock_get.return_value = []
        mock_find.return_value = None
        mock_fuzzy.return_value = []

        msg = _make_message("/lookup Несуществующий")
        state = _make_state()

        asyncio.run(cmd_lookup(msg, state))

        text = msg.answer.call_args[0][0]
        assert "не найден" in text

    def test_lookup_no_args_shows_usage(self):
        from telegram_bot.flow_callbacks import cmd_lookup

        msg = _make_message("/lookup")
        state = _make_state()

        asyncio.run(cmd_lookup(msg, state))

        msg.answer.assert_awaited_once()
        assert "Использование" in msg.answer.call_args[0][0]

    @patch("telegram_bot.flow_callbacks.get_contractors")
    @patch("telegram_bot.flow_callbacks.find_contractor")
    def test_lookup_no_mags_field(self, mock_find, mock_get):
        from telegram_bot.flow_callbacks import cmd_lookup

        contractor = _global(mags="")
        mock_get.return_value = [contractor]
        mock_find.return_value = contractor

        msg = _make_message("/lookup Test")
        state = _make_state()

        asyncio.run(cmd_lookup(msg, state))

        text = msg.answer.call_args[0][0]
        assert "Издания" not in text

    @patch("telegram_bot.flow_callbacks.get_contractors")
    @patch("telegram_bot.flow_callbacks.find_contractor")
    def test_lookup_no_email_field(self, mock_find, mock_get):
        from telegram_bot.flow_callbacks import cmd_lookup

        contractor = _global(email="")
        mock_get.return_value = [contractor]
        mock_find.return_value = contractor

        msg = _make_message("/lookup Test")
        state = _make_state()

        asyncio.run(cmd_lookup(msg, state))

        text = msg.answer.call_args[0][0]
        assert "Email" not in text


# ===================================================================
#  _parse_with_llm — payment validation logging
# ===================================================================

class TestParseWithLlm:

    _SVC = "backend.domain.services.contractor_service"

    @patch(f"{_SVC}.DbGateway")
    @patch(f"{_SVC}.parse_contractor_data")
    def test_successful_parse_logs_to_db(self, mock_parse, mock_db_cls):
        from backend.domain.services.contractor_service import parse_registration_data

        mock_parse.return_value = {"name_ru": "Иван Иванов", "inn": "123456789012"}
        mock_db = mock_db_cls.return_value
        mock_db.log_payment_validation.return_value = "val-001"

        result = parse_registration_data("Иван Иванов ИНН 123456789012", ContractorType.SAMOZANYATY)

        assert result["name_ru"] == "Иван Иванов"
        assert result["_validation_id"] == "val-001"
        mock_db.log_payment_validation.assert_called_once()
        call_kwargs = mock_db.log_payment_validation.call_args[1]
        assert call_kwargs["contractor_type"] == "самозанятый"
        assert "Иван Иванов" in call_kwargs["input_text"]

    @patch(f"{_SVC}.DbGateway")
    @patch(f"{_SVC}.parse_contractor_data")
    def test_parse_error_skips_db_log(self, mock_parse, mock_db_cls):
        from backend.domain.services.contractor_service import parse_registration_data

        mock_parse.return_value = {"parse_error": "Could not parse"}

        result = parse_registration_data("gibberish", ContractorType.SAMOZANYATY)

        assert "parse_error" in result
        mock_db_cls.return_value.log_payment_validation.assert_not_called()

    @patch(f"{_SVC}.DbGateway")
    @patch(f"{_SVC}.parse_contractor_data")
    def test_db_log_failure_still_returns_result(self, mock_parse, mock_db_cls):
        from backend.domain.services.contractor_service import parse_registration_data

        mock_parse.return_value = {"name_ru": "Test"}
        mock_db_cls.return_value.log_payment_validation.side_effect = RuntimeError("DB down")

        result = parse_registration_data("test", ContractorType.SAMOZANYATY)

        assert result["name_ru"] == "Test"
        assert "_validation_id" not in result

    @patch(f"{_SVC}.DbGateway")
    @patch(f"{_SVC}.parse_contractor_data")
    def test_passes_context_with_collected_data(self, mock_parse, mock_db_cls):
        from backend.domain.services.contractor_service import parse_registration_data

        mock_parse.return_value = {"inn": "111222333444"}
        mock_db_cls.return_value.log_payment_validation.return_value = "v1"

        collected = {"name_ru": "Иван", "email": "ivan@test.ru"}
        result = parse_registration_data(
            "ИНН 111222333444", ContractorType.SAMOZANYATY,
            collected=collected,
        )

        # parse_contractor_data should have been called with context
        call_args = mock_parse.call_args
        context = call_args[0][2]
        assert "Иван" in context
        assert "ivan@test.ru" in context

    @patch(f"{_SVC}.DbGateway")
    @patch(f"{_SVC}.parse_contractor_data")
    def test_passes_warnings_in_context(self, mock_parse, mock_db_cls):
        from backend.domain.services.contractor_service import parse_registration_data

        mock_parse.return_value = {"inn": "valid"}
        mock_db_cls.return_value.log_payment_validation.return_value = "v2"

        warnings = ["ИНН: должен быть 12 цифр"]
        result = parse_registration_data(
            "ИНН valid", ContractorType.SAMOZANYATY,
            collected={"name_ru": "Test"}, warnings=warnings,
        )

        context = mock_parse.call_args[0][2]
        assert "ошибки валидации" in context
        assert "12 цифр" in context

    @patch(f"{_SVC}.DbGateway")
    @patch(f"{_SVC}.parse_contractor_data")
    def test_ip_contractor_type(self, mock_parse, mock_db_cls):
        from backend.domain.services.contractor_service import parse_registration_data

        mock_parse.return_value = {"name_ru": "ИП Петров"}
        mock_db_cls.return_value.log_payment_validation.return_value = "v3"

        result = parse_registration_data("ИП Петров", ContractorType.IP)

        call_kwargs = mock_db_cls.return_value.log_payment_validation.call_args[1]
        assert call_kwargs["contractor_type"] == "ИП"

    @patch(f"{_SVC}.DbGateway")
    @patch(f"{_SVC}.parse_contractor_data")
    def test_global_contractor_type(self, mock_parse, mock_db_cls):
        from backend.domain.services.contractor_service import parse_registration_data

        mock_parse.return_value = {"name_en": "John Smith"}
        mock_db_cls.return_value.log_payment_validation.return_value = "v4"

        result = parse_registration_data("John Smith", ContractorType.GLOBAL)

        call_kwargs = mock_db_cls.return_value.log_payment_validation.call_args[1]
        assert call_kwargs["contractor_type"] == "global"

    @patch(f"{_SVC}.DbGateway")
    @patch(f"{_SVC}.parse_contractor_data")
    def test_parsed_json_in_db_call(self, mock_parse, mock_db_cls):
        from backend.domain.services.contractor_service import parse_registration_data

        mock_parse.return_value = {"name_ru": "Тест", "inn": "123"}
        mock_db_cls.return_value.log_payment_validation.return_value = "v5"

        parse_registration_data("Тест ИНН 123", ContractorType.SAMOZANYATY)

        call_kwargs = mock_db_cls.return_value.log_payment_validation.call_args[1]
        parsed_json = json.loads(call_kwargs["parsed_json"])
        assert parsed_json["name_ru"] == "Тест"
        assert parsed_json["inn"] == "123"


# ===================================================================
#  _dispatch_group_command — text rewriting
# ===================================================================

class TestDispatchGroupCommand:

    @patch("telegram_bot.flow_callbacks.run_healthchecks")
    @patch("telegram_bot.flow_callbacks.format_healthcheck_results")
    @patch("telegram_bot.flow_callbacks.bot")
    def test_rewrites_message_text_with_args(self, mock_bot, mock_format, mock_run):
        from telegram_bot.flow_callbacks import _dispatch_group_command

        mock_run.return_value = []
        mock_format.return_value = "OK"
        mock_bot.send_chat_action = AsyncMock()

        msg = _make_message("@republic_bot проверь сайт")
        original_text = msg.text
        state = _make_state()

        asyncio.run(_dispatch_group_command("health", "extra", msg, state))

        # After dispatch, original text should be restored
        assert msg.text == original_text

    @patch("telegram_bot.flow_callbacks.run_healthchecks")
    @patch("telegram_bot.flow_callbacks.format_healthcheck_results")
    @patch("telegram_bot.flow_callbacks.bot")
    def test_rewrites_message_text_without_args(self, mock_bot, mock_format, mock_run):
        from telegram_bot.flow_callbacks import _dispatch_group_command

        mock_run.return_value = []
        mock_format.return_value = "OK"
        mock_bot.send_chat_action = AsyncMock()

        msg = _make_message("@republic_bot проверь")
        original_text = msg.text
        state = _make_state()

        asyncio.run(_dispatch_group_command("health", "", msg, state))

        assert msg.text == original_text

    def test_unknown_command_does_nothing(self):
        from telegram_bot.flow_callbacks import _dispatch_group_command

        msg = _make_message("text")
        state = _make_state()

        asyncio.run(_dispatch_group_command("nonexistent", "", msg, state))

        msg.answer.assert_not_awaited()

    @patch("telegram_bot.flow_callbacks.run_healthchecks")
    @patch("telegram_bot.flow_callbacks.format_healthcheck_results")
    @patch("telegram_bot.flow_callbacks.bot")
    def test_restores_text_even_on_error(self, mock_bot, mock_format, mock_run):
        from telegram_bot.flow_callbacks import _dispatch_group_command

        mock_run.side_effect = RuntimeError("fail")
        mock_bot.send_chat_action = AsyncMock()

        msg = _make_message("original text")
        state = _make_state()

        # cmd_health wraps in asyncio.to_thread, so the error propagates
        with pytest.raises(RuntimeError):
            asyncio.run(_dispatch_group_command("health", "", msg, state))

        assert msg.text == "original text"
