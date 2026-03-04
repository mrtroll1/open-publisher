"""Tests for telegram_bot/handler_utils.py — pure helper functions."""

from unittest.mock import patch


# ===================================================================
#  _split_text
# ===================================================================

class TestSplitText:

    def _split(self, text, limit=4096):
        from telegram_bot.handler_utils import _split_text
        return _split_text(text, limit)

    def test_short_text_returns_single_chunk(self):
        result = self._split("Hello, world!")
        assert result == ["Hello, world!"]

    def test_empty_text(self):
        result = self._split("")
        assert result == [""]

    def test_exact_limit(self):
        text = "A" * 4096
        result = self._split(text)
        assert result == [text]

    def test_splits_at_newline(self):
        line = "X" * 30
        text = f"{line}\n{line}\n{line}"
        result = self._split(text, limit=35)
        assert len(result) == 3
        assert result[0] == line
        assert result[1] == line
        assert result[2] == line

    def test_splits_at_limit_when_no_newline(self):
        text = "A" * 100
        result = self._split(text, limit=40)
        assert result[0] == "A" * 40
        assert result[1] == "A" * 40
        assert result[2] == "A" * 20

    def test_strips_leading_newlines_between_chunks(self):
        # Split cuts at last \n before limit, leaving leading \n's on next chunk
        # which then get stripped by lstrip("\n")
        text = "A" * 10 + "\n" + "B" * 10 + "\n\n" + "C" * 10
        result = self._split(text, limit=15)
        # First chunk: "A"*10 + "\n" + "BBB" → cut at last \n before 15 = pos 10
        # -> chunk = "A"*10, rest = "B"*10 + "\n\n" + "C"*10
        assert result[0] == "A" * 10
        assert "B" * 10 in result[1]

    def test_multi_chunk_preserves_content(self):
        text = "\n".join(f"line-{i}" for i in range(50))
        result = self._split(text, limit=100)
        reassembled = "\n".join(result)
        assert reassembled == text


# ===================================================================
#  _parse_flags
# ===================================================================

class TestParseFlags:

    def _parse(self, text):
        from telegram_bot.handler_utils import _parse_flags
        return _parse_flags(text)

    def test_no_flags(self):
        verbose, expert, rest = self._parse("some text here")
        assert verbose is False
        assert expert is False
        assert rest == "some text here"

    def test_verbose_short(self):
        verbose, expert, rest = self._parse("-v some text")
        assert verbose is True
        assert expert is False
        assert rest == "some text"

    def test_verbose_long(self):
        verbose, expert, rest = self._parse("verbose some text")
        assert verbose is True
        assert expert is False
        assert rest == "some text"

    def test_expert_short(self):
        verbose, expert, rest = self._parse("-e some text")
        assert verbose is False
        assert expert is True
        assert rest == "some text"

    def test_expert_long(self):
        verbose, expert, rest = self._parse("expert some text")
        assert verbose is False
        assert expert is True
        assert rest == "some text"

    def test_both_flags(self):
        verbose, expert, rest = self._parse("-v -e some text")
        assert verbose is True
        assert expert is True
        assert rest == "some text"

    def test_both_flags_reversed(self):
        verbose, expert, rest = self._parse("-e -v some text")
        assert verbose is True
        assert expert is True
        assert rest == "some text"

    def test_empty_text(self):
        verbose, expert, rest = self._parse("")
        assert verbose is False
        assert expert is False
        assert rest == ""

    def test_flag_only_no_rest(self):
        verbose, expert, rest = self._parse("-v ")
        assert verbose is True
        assert rest == ""

    def test_flag_not_at_start_is_ignored(self):
        verbose, expert, rest = self._parse("something -v other")
        assert verbose is False
        assert rest == "something -v other"


# ===================================================================
#  parse_month_arg
# ===================================================================

class TestParseMonthArg:

    def _parse(self, args):
        from telegram_bot.handler_utils import parse_month_arg
        return parse_month_arg(args)

    @patch("telegram_bot.handler_utils.prev_month", return_value="2026-02")
    def test_no_args_returns_prev_month(self, _mock):
        result = self._parse(["/cmd"])
        assert result == "2026-02"

    def test_with_month_arg(self):
        result = self._parse(["/cmd", "2026-01"])
        assert result == "2026-01"

    def test_strips_whitespace(self):
        result = self._parse(["/cmd", "  2026-03  "])
        assert result == "2026-03"
