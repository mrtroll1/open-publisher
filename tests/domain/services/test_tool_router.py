"""Tests for ToolRouter — decides which tools to invoke."""

from unittest.mock import MagicMock, patch

from backend.domain.services.tool_router import ToolRouter, ToolCall


def _make_router(gemini_response, available_tools=None):
    gemini = MagicMock()
    gemini.call.return_value = gemini_response
    with patch("backend.domain.services.tool_router.load_template", return_value="prompt"):
        router = ToolRouter(gemini=gemini, available_tools=available_tools or ["rag", "republic_db", "redefine_db"])
    return router, gemini


class TestRoute:
    def test_routes_to_db(self):
        router, _ = _make_router(
            {"tools": [{"name": "republic_db", "query": "today's posts"}]}
        )
        with patch("backend.domain.services.tool_router.load_template", return_value="prompt"):
            calls = router.route("что вышло сегодня?")
        names = [c.name for c in calls]
        assert "republic_db" in names
        # RAG always included as fallback
        assert "rag" in names

    def test_routes_to_rag_only(self):
        router, _ = _make_router(
            {"tools": [{"name": "rag", "query": "what is Republic?"}]}
        )
        with patch("backend.domain.services.tool_router.load_template", return_value="prompt"):
            calls = router.route("что такое Republic?")
        assert len(calls) == 1
        assert calls[0].name == "rag"

    def test_routes_to_multiple(self):
        router, _ = _make_router(
            {"tools": [
                {"name": "republic_db", "query": "author of election article"},
                {"name": "rag", "query": "publication rules"},
            ]}
        )
        with patch("backend.domain.services.tool_router.load_template", return_value="prompt"):
            calls = router.route("кто автор и какие правила?")
        names = [c.name for c in calls]
        assert "republic_db" in names
        assert "rag" in names

    def test_filters_unavailable_tools(self):
        router, _ = _make_router(
            {"tools": [{"name": "redefine_db", "query": "subscription"}]},
            available_tools=["rag"],  # redefine_db not available
        )
        with patch("backend.domain.services.tool_router.load_template", return_value="prompt"):
            calls = router.route("подписка")
        # Should fall back to RAG since redefine_db is not in available_tools
        assert all(c.name == "rag" for c in calls)

    def test_empty_response_falls_back_to_rag(self):
        router, _ = _make_router({"tools": []})
        with patch("backend.domain.services.tool_router.load_template", return_value="prompt"):
            calls = router.route("anything")
        assert len(calls) == 1
        assert calls[0].name == "rag"

    def test_gemini_failure_falls_back_to_rag(self):
        gemini = MagicMock()
        gemini.call.side_effect = Exception("API error")
        router = ToolRouter(gemini=gemini, available_tools=["rag", "republic_db"])
        # route should propagate the exception — caller (generate_nl_reply) catches it
        import pytest
        with pytest.raises(Exception):
            with patch("backend.domain.services.tool_router.load_template", return_value="prompt"):
                router.route("test")
