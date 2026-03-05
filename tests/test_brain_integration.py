"""Smoke tests for brain wiring — verify controllers and route registry work."""

from unittest.mock import MagicMock, patch

import pytest

from backend.brain.base_controller import (
    BaseController,
    BasePreparer,
    BaseUseCase,
    GenAIUseCase,
    PassThroughPreparer,
    StubUseCase,
)
from backend.brain.routes import ROUTE_DEFINITIONS, ROUTES, Route, register_route


class TestBaseController:
    def test_passthrough_preparer(self):
        p = PassThroughPreparer()
        assert p.prepare("hello", {}, {}) == "hello"

    def test_stub_use_case(self):
        stub = StubUseCase("test msg")
        result = stub.execute("input", {}, {})
        assert result["status"] == "stub"
        assert result["message"] == "test msg"

    def test_genai_use_case_delegates(self):
        mock_genai = MagicMock()
        mock_genai.run.return_value = {"reply": "ok"}
        uc = GenAIUseCase(mock_genai)
        result = uc.execute("hello", {"env_key": 1}, {"user_key": 2})
        mock_genai.run.assert_called_once_with("hello", {"env": {"env_key": 1}, "user": {"user_key": 2}})
        assert result == {"reply": "ok"}

    def test_controller_chains_preparer_and_use_case(self):
        mock_uc = MagicMock()
        mock_uc.execute.return_value = "done"
        ctrl = BaseController(PassThroughPreparer(), mock_uc)
        result = ctrl.execute("input", {}, {})
        mock_uc.execute.assert_called_once_with("input", {}, {})
        assert result == "done"


class TestRouteDefinitions:
    def test_route_definitions_not_empty(self):
        assert len(ROUTE_DEFINITIONS) > 0

    def test_all_definitions_have_required_fields(self):
        for defn in ROUTE_DEFINITIONS:
            assert "name" in defn
            assert "description" in defn
            assert isinstance(defn.get("permissions", set()), set)

    def test_expected_routes_present(self):
        names = {d["name"] for d in ROUTE_DEFINITIONS}
        expected = {"conversation", "support", "code", "health", "teach", "search",
                    "query", "invoice", "budget", "ingest", "inbox"}
        assert expected.issubset(names)

    def test_register_route(self):
        ROUTES.clear()
        ctrl = BaseController(PassThroughPreparer(), StubUseCase())
        route = Route(name="test_route", controller=ctrl, description="test")
        register_route(route)
        assert "test_route" in ROUTES
        assert ROUTES["test_route"].description == "test"
        ROUTES.pop("test_route", None)


class TestCommandControllerFactories:
    """Test that controller factory functions return valid BaseController instances."""

    def test_conversation_controller(self):
        from backend.commands.conversation import create_conversation_controller
        mock_genai = MagicMock()
        ctrl = create_conversation_controller(mock_genai)
        assert isinstance(ctrl, BaseController)

    def test_support_controller(self):
        from backend.commands.support import create_support_controller
        mock_genai = MagicMock()
        ctrl = create_support_controller(mock_genai)
        assert isinstance(ctrl, BaseController)

    def test_code_controller(self):
        from backend.commands.code import create_code_controller
        ctrl = create_code_controller()
        assert isinstance(ctrl, BaseController)

    def test_health_controller(self):
        from backend.commands.health import create_health_controller
        ctrl = create_health_controller()
        assert isinstance(ctrl, BaseController)

    def test_teach_controller(self):
        from backend.commands.teach import create_teach_controller
        ctrl = create_teach_controller(MagicMock(), MagicMock())
        assert isinstance(ctrl, BaseController)

    def test_search_controller(self):
        from backend.commands.search import create_search_controller
        ctrl = create_search_controller(MagicMock())
        assert isinstance(ctrl, BaseController)

    def test_query_controller(self):
        from backend.commands.query import create_query_controller
        ctrl = create_query_controller(MagicMock())
        assert isinstance(ctrl, BaseController)

    def test_ingest_controller(self):
        from backend.commands.ingest import create_ingest_controller
        ctrl = create_ingest_controller(MagicMock(), MagicMock())
        assert isinstance(ctrl, BaseController)

    def test_contractor_controller(self):
        from backend.commands.contractor import create_contractor_controller
        ctrl = create_contractor_controller()
        assert isinstance(ctrl, BaseController)


class TestParseFlags:
    def test_no_flags(self):
        from backend.commands.utils import parse_flags
        v, e, text = parse_flags("hello world")
        assert not v and not e and text == "hello world"

    def test_verbose(self):
        from backend.commands.utils import parse_flags
        v, e, text = parse_flags("-v some question")
        assert v and not e and text == "some question"

    def test_expert(self):
        from backend.commands.utils import parse_flags
        v, e, text = parse_flags("-e some question")
        assert not v and e and text == "some question"

    def test_both(self):
        from backend.commands.utils import parse_flags
        v, e, text = parse_flags("-v -e the rest")
        assert v and e and text == "the rest"

    def test_empty(self):
        from backend.commands.utils import parse_flags
        v, e, text = parse_flags("")
        assert not v and not e and text == ""
