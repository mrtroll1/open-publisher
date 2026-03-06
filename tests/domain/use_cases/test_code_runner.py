"""Tests for backend/domain/use_cases.run_claude_code.py"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from backend.commands.code import (
    _EXPLORE_USER_PREFIX, _EXPLORE_EXPERT_PREFIX, _CHANGES_PREFIX,
    run_claude_code, CodeResult,
)


# ===================================================================
#  run_claude_code()
# ===================================================================

class TestRunClaudeCode:

    @patch("backend.commands.code.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="Here is the answer.",
            stderr="",
        )
        result = run_claude_code("what is this?")
        assert isinstance(result, CodeResult)
        assert result.text == "Here is the answer."

    @patch("backend.commands.code.subprocess.run")
    def test_verbose_no_prefix(self, mock_run):
        mock_run.return_value = MagicMock(stdout="ok", stderr="")
        run_claude_code("question", verbose=True)
        call_args = mock_run.call_args
        prompt_arg = call_args[0][0][2]  # ["claude", "-p", <prompt>, ...]
        assert prompt_arg == "question"

    @patch("backend.commands.code.subprocess.run")
    def test_explore_user_prefix(self, mock_run):
        mock_run.return_value = MagicMock(stdout="ok", stderr="")
        run_claude_code("question", verbose=False, mode="explore")
        prompt_arg = mock_run.call_args[0][0][2]
        assert prompt_arg.startswith(_EXPLORE_USER_PREFIX)
        assert "question" in prompt_arg

    @patch("backend.commands.code.subprocess.run")
    def test_explore_expert_prefix(self, mock_run):
        mock_run.return_value = MagicMock(stdout="ok", stderr="")
        run_claude_code("question", verbose=False, expert=True, mode="explore")
        prompt_arg = mock_run.call_args[0][0][2]
        assert prompt_arg.startswith(_EXPLORE_EXPERT_PREFIX)

    @patch("backend.commands.code.subprocess.run")
    def test_changes_prefix(self, mock_run):
        mock_run.return_value = MagicMock(stdout="ok", stderr="")
        run_claude_code("question", verbose=False, mode="changes")
        prompt_arg = mock_run.call_args[0][0][2]
        assert prompt_arg.startswith(_CHANGES_PREFIX)

    @patch("backend.commands.code.subprocess.run")
    def test_long_output_not_truncated(self, mock_run):
        long_text = "x" * 5000
        mock_run.return_value = MagicMock(stdout=long_text, stderr="")
        result = run_claude_code("q")
        assert len(result.text) == 5000

    @patch("backend.commands.code.subprocess.run")
    def test_empty_stdout_uses_stderr(self, mock_run):
        mock_run.return_value = MagicMock(stdout="", stderr="some error info")
        result = run_claude_code("q")
        assert result.text == "stderr: some error info"

    @patch("backend.commands.code.subprocess.run")
    def test_empty_both(self, mock_run):
        mock_run.return_value = MagicMock(stdout="", stderr="")
        result = run_claude_code("q")
        assert result.text == "(пустой ответ от Claude Code)"

    @patch("backend.commands.code.subprocess.run")
    def test_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=300)
        result = run_claude_code("q")
        assert "Таймаут" in result.text

    @patch("backend.commands.code.subprocess.run")
    def test_file_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        result = run_claude_code("q")
        assert "не найден" in result.text

    @patch("backend.commands.code.subprocess.run")
    def test_generic_exception(self, mock_run):
        mock_run.side_effect = RuntimeError("boom")
        result = run_claude_code("q")
        assert "Ошибка выполнения" in result.text
        assert "boom" in result.text

    @patch("backend.commands.code.subprocess.run")
    def test_session_id_none_in_simple_mode(self, mock_run):
        mock_run.return_value = MagicMock(stdout="ok", stderr="")
        result = run_claude_code("q")
        assert result.session_id is None
