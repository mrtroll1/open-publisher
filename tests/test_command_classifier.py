"""Tests for backend/domain/command_classifier.py and classify_command() compose."""

import pytest
from unittest.mock import MagicMock

from backend.domain.command_classifier import ClassifiedCommand, CommandClassifier
from backend.domain.compose_request import _MODELS, classify_command


SAMPLE_COMMANDS = {
    "health": "Проверка доступности сайтов и подов",
    "tech_support": "Задать вопрос по техподдержке",
    "code": "Запустить Claude Code",
}


# ===================================================================
#  ClassifiedCommand dataclass
# ===================================================================

class TestClassifiedCommand:

    def test_fields(self):
        cc = ClassifiedCommand(command="health", args="")
        assert cc.command == "health"
        assert cc.args == ""

    def test_with_args(self):
        cc = ClassifiedCommand(command="code", args="check tests")
        assert cc.command == "code"
        assert cc.args == "check tests"


# ===================================================================
#  CommandClassifier.classify() — mocked Gemini
# ===================================================================

class TestCommandClassifier:

    def _make_classifier(self, gemini_return: dict) -> CommandClassifier:
        gemini = MagicMock()
        gemini.call.return_value = gemini_return
        return CommandClassifier(gemini)

    # -- Russian NL inputs map to correct commands ---

    def test_russian_nl_health(self):
        clf = self._make_classifier({"command": "health", "args": ""})
        result = clf.classify("у нас сайт лежит", SAMPLE_COMMANDS)
        assert result is not None
        assert result.command == "health"
        assert result.args == ""

    def test_russian_nl_tech_support(self):
        clf = self._make_classifier({"command": "tech_support", "args": "как настроить подписку"})
        result = clf.classify("как настроить подписку", SAMPLE_COMMANDS)
        assert result is not None
        assert result.command == "tech_support"
        assert result.args == "как настроить подписку"

    def test_russian_nl_code(self):
        clf = self._make_classifier({"command": "code", "args": "проверь тесты"})
        result = clf.classify("запусти клод чтобы проверить тесты", SAMPLE_COMMANDS)
        assert result is not None
        assert result.command == "code"
        assert result.args == "проверь тесты"

    # -- Returns None for irrelevant messages ---

    def test_returns_none_when_command_is_null(self):
        clf = self._make_classifier({"command": None, "args": ""})
        result = clf.classify("что нового?", SAMPLE_COMMANDS)
        assert result is None

    def test_returns_none_when_command_missing_from_response(self):
        clf = self._make_classifier({"args": ""})
        result = clf.classify("привет", SAMPLE_COMMANDS)
        assert result is None

    def test_returns_none_when_command_not_in_available(self):
        clf = self._make_classifier({"command": "unknown_cmd", "args": ""})
        result = clf.classify("сделай что-то", SAMPLE_COMMANDS)
        assert result is None

    # -- Args default ---

    def test_missing_args_defaults_to_empty(self):
        clf = self._make_classifier({"command": "health"})
        result = clf.classify("проверь сайт", SAMPLE_COMMANDS)
        assert result is not None
        assert result.args == ""

    # -- Gemini is called with correct prompt/model ---

    def test_gemini_called_with_prompt_and_model(self):
        gemini = MagicMock()
        gemini.call.return_value = {"command": "health", "args": ""}
        clf = CommandClassifier(gemini)
        clf.classify("проверь сайт", SAMPLE_COMMANDS)

        gemini.call.assert_called_once()
        call_args = gemini.call.call_args
        prompt = call_args[0][0]
        model = call_args[0][1]
        assert isinstance(prompt, str)
        assert model == _MODELS["classify_command"]

    def test_prompt_contains_user_text(self):
        gemini = MagicMock()
        gemini.call.return_value = {"command": None, "args": ""}
        clf = CommandClassifier(gemini)
        clf.classify("у нас сайт лежит", SAMPLE_COMMANDS)

        prompt = gemini.call.call_args[0][0]
        assert "у нас сайт лежит" in prompt

    def test_prompt_contains_command_descriptions(self):
        gemini = MagicMock()
        gemini.call.return_value = {"command": None, "args": ""}
        clf = CommandClassifier(gemini)
        clf.classify("test", SAMPLE_COMMANDS)

        prompt = gemini.call.call_args[0][0]
        assert "health" in prompt
        assert "tech_support" in prompt
        assert "code" in prompt

    # -- Subset of available commands ---

    def test_only_available_commands_accepted(self):
        subset = {"health": "Check health"}
        clf = self._make_classifier({"command": "code", "args": ""})
        result = clf.classify("запусти клод", subset)
        assert result is None


# ===================================================================
#  classify_command() compose function
# ===================================================================

class TestClassifyCommandCompose:

    def test_returns_tuple(self):
        prompt, model, keys = classify_command("some text", "- health")
        assert isinstance(prompt, str)
        assert isinstance(model, str)
        assert isinstance(keys, list)

    def test_model_correct(self):
        _, model, _ = classify_command("text", "desc")
        assert model == _MODELS["classify_command"]

    def test_keys(self):
        _, _, keys = classify_command("text", "desc")
        assert keys == ["command", "args"]

    def test_prompt_contains_text(self):
        prompt, _, _ = classify_command("у нас сайт лежит", "- health — check")
        assert "у нас сайт лежит" in prompt

    def test_prompt_contains_commands(self):
        prompt, _, _ = classify_command("text", "- health — Проверка")
        assert "health" in prompt
        assert "Проверка" in prompt
