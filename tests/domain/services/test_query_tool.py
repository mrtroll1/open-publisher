# TODO: rewrite test for new brain/ architecture
"""Tests for QueryTool — NL to SQL via Gemini."""

import pytest
from unittest.mock import MagicMock, patch

from backend.domain.services.query_tool import QueryTool


def _make_tool(gemini_response=None, gateway_rows=None, gateway_error=None):
    gateway = MagicMock()
    gateway.available = True
    if gateway_error:
        gateway.execute.side_effect = gateway_error
    else:
        gateway.execute.return_value = gateway_rows or []

    gemini = MagicMock()
    gemini.call.return_value = gemini_response or {"sql": "SELECT 1", "explanation": "test"}

    with patch("backend.domain.services.query_tool.load_template", return_value="prompt"):
        tool = QueryTool(gateway, "db-query/test-schema.md", gemini=gemini)
    return tool, gateway, gemini


class TestQuery:
    def test_successful_query(self):
        tool, gw, _ = _make_tool(
            gemini_response={"sql": "SELECT id FROM posts", "explanation": "get posts"},
            gateway_rows=[{"id": 1}, {"id": 2}],
        )
        with patch("backend.domain.services.query_tool.load_template", return_value="prompt"):
            result = tool.query("what posts?")
        assert result["rows"] == [{"id": 1}, {"id": 2}]
        assert result["sql"] == "SELECT id FROM posts"
        assert result["error"] == ""

    def test_no_sql_generated(self):
        tool, _, _ = _make_tool(
            gemini_response={"sql": "", "explanation": "can't do it"},
        )
        with patch("backend.domain.services.query_tool.load_template", return_value="prompt"):
            result = tool.query("impossible question")
        assert result["rows"] == []
        assert "LLM did not produce" in result["error"]

    def test_db_error_returned(self):
        tool, _, _ = _make_tool(
            gemini_response={"sql": "SELECT bad", "explanation": "test"},
            gateway_error=Exception("column 'bad' not found"),
        )
        with patch("backend.domain.services.query_tool.load_template", return_value="prompt"):
            result = tool.query("bad query")
        assert result["rows"] == []
        assert "bad" in result["error"]

    def test_row_limit(self):
        many_rows = [{"id": i} for i in range(100)]
        tool, _, _ = _make_tool(
            gemini_response={"sql": "SELECT id FROM t", "explanation": "all"},
            gateway_rows=many_rows,
        )
        with patch("backend.domain.services.query_tool.load_template", return_value="prompt"):
            result = tool.query("all rows")
        assert len(result["rows"]) == 50
