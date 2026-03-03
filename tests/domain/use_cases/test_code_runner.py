"""Tests for backend/domain/code_runner.py"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from backend.domain.code_runner import (
    _EXPLORE_USER_PREFIX, _EXPLORE_EXPERT_PREFIX, _CHANGES_PREFIX,
    run_claude_code,
)


# ===================================================================
#  run_claude_code()
# ===================================================================

class TestRunClaudeCode:

    @patch("backend.domain.code_runner.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="Here is the answer.",
            stderr="",
        )
        result = run_claude_code("what is this?")
        assert result == "Here is the answer."

    @patch("backend.domain.code_runner.subprocess.run")
    def test_verbose_no_prefix(self, mock_run):
        mock_run.return_value = MagicMock(stdout="ok", stderr="")
        run_claude_code("question", verbose=True)
        call_args = mock_run.call_args
        prompt_arg = call_args[0][0][2]  # ["claude", "-p", <prompt>, ...]
        assert prompt_arg == "question"

    @patch("backend.domain.code_runner.subprocess.run")
    def test_explore_user_prefix(self, mock_run):
        mock_run.return_value = MagicMock(stdout="ok", stderr="")
        run_claude_code("question", verbose=False, mode="explore")
        prompt_arg = mock_run.call_args[0][0][2]
        assert prompt_arg.startswith(_EXPLORE_USER_PREFIX)
        assert "question" in prompt_arg

    @patch("backend.domain.code_runner.subprocess.run")
    def test_explore_expert_prefix(self, mock_run):
        mock_run.return_value = MagicMock(stdout="ok", stderr="")
        run_claude_code("question", verbose=False, expert=True, mode="explore")
        prompt_arg = mock_run.call_args[0][0][2]
        assert prompt_arg.startswith(_EXPLORE_EXPERT_PREFIX)

    @patch("backend.domain.code_runner.subprocess.run")
    def test_changes_prefix(self, mock_run):
        mock_run.return_value = MagicMock(stdout="ok", stderr="")
        run_claude_code("question", verbose=False, mode="changes")
        prompt_arg = mock_run.call_args[0][0][2]
        assert prompt_arg.startswith(_CHANGES_PREFIX)

    @patch("backend.domain.code_runner.subprocess.run")
    def test_long_output_not_truncated(self, mock_run):
        long_text = "x" * 5000
        mock_run.return_value = MagicMock(stdout=long_text, stderr="")
        result = run_claude_code("q")
        assert len(result) == 5000

    @patch("backend.domain.code_runner.subprocess.run")
    def test_empty_stdout_uses_stderr(self, mock_run):
        mock_run.return_value = MagicMock(stdout="", stderr="some error info")
        result = run_claude_code("q")
        assert result == "stderr: some error info"

    @patch("backend.domain.code_runner.subprocess.run")
    def test_empty_both(self, mock_run):
        mock_run.return_value = MagicMock(stdout="", stderr="")
        result = run_claude_code("q")
        assert result == "(пустой ответ от Claude Code)"

    @patch("backend.domain.code_runner.subprocess.run")
    def test_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=300)
        result = run_claude_code("q")
        assert "Таймаут" in result

    @patch("backend.domain.code_runner.subprocess.run")
    def test_file_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        result = run_claude_code("q")
        assert "не найден" in result

    @patch("backend.domain.code_runner.subprocess.run")
    def test_generic_exception(self, mock_run):
        mock_run.side_effect = RuntimeError("boom")
        result = run_claude_code("q")
        assert "Ошибка выполнения" in result
        assert "boom" in result
