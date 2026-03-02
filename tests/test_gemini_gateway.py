"""Tests for GeminiGateway.call() task-based classification logging."""

import sys
from unittest.mock import MagicMock, patch

import pytest

from backend.infrastructure.gateways.gemini_gateway import GeminiGateway

_mock_genai = MagicMock()


@pytest.fixture(autouse=True)
def _patch_genai():
    """Ensure our mock is active in sys.modules for each test."""
    _mock_genai.reset_mock()
    with patch.dict(sys.modules, {"google.genai": _mock_genai}):
        yield


def _setup_genai_response(response_text: str = '{"result": "ok"}'):
    """Configure the stubbed genai module to return the given text."""
    mock_response = MagicMock()
    mock_response.text = response_text
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    _mock_genai.Client.return_value = mock_client


class TestGeminiGatewayTaskLogging:

    def setup_method(self):
        _setup_genai_response('{"result": "ok"}')

    @patch("backend.infrastructure.gateways.db_gateway.DbGateway")
    def test_call_with_task_logs_classification(self, MockDbGwClass):
        mock_db = MockDbGwClass.return_value
        gw = GeminiGateway()

        result = gw.call("test prompt", model="gemini-2.5-flash", task="INBOX_CLASSIFY")

        assert result == {"result": "ok"}
        mock_db.log_classification.assert_called_once()
        call_args = mock_db.log_classification.call_args[0]
        assert call_args[0] == "INBOX_CLASSIFY"
        assert call_args[1] == "gemini-2.5-flash"
        assert call_args[2] == "test prompt"
        assert '"result": "ok"' in call_args[3]
        assert isinstance(call_args[4], int)
        assert call_args[4] >= 0

    @patch("backend.infrastructure.gateways.db_gateway.DbGateway")
    def test_call_without_task_does_not_log(self, MockDbGwClass):
        gw = GeminiGateway()

        result = gw.call("test prompt", model="gemini-2.5-flash")

        assert result == {"result": "ok"}
        MockDbGwClass.assert_not_called()

    @patch("backend.infrastructure.gateways.db_gateway.DbGateway")
    def test_call_with_task_uses_default_model(self, MockDbGwClass):
        mock_db = MockDbGwClass.return_value
        gw = GeminiGateway(model="gemini-2.5-flash")

        gw.call("prompt", task="COMMAND_CLASSIFY")

        call_args = mock_db.log_classification.call_args[0]
        assert call_args[1] == "gemini-2.5-flash"

    @patch("backend.infrastructure.gateways.db_gateway.DbGateway")
    def test_call_with_task_db_failure_does_not_raise(self, MockDbGwClass):
        mock_db = MockDbGwClass.return_value
        mock_db.log_classification.side_effect = Exception("DB connection failed")
        gw = GeminiGateway()

        result = gw.call("prompt", task="INBOX_CLASSIFY")

        assert result == {"result": "ok"}
