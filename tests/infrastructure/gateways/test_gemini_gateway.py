"""Tests for GeminiGateway.call() — pure LLM wrapper, no DB logging."""

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


class TestGeminiGatewayCall:

    def setup_method(self):
        _setup_genai_response('{"result": "ok"}')

    def test_call_returns_parsed_json(self):
        gw = GeminiGateway()
        result = gw.call("test prompt", model="gemini-2.5-flash")
        assert result == {"result": "ok"}

    def test_call_uses_default_model(self):
        gw = GeminiGateway(model="gemini-2.5-flash")
        result = gw.call("prompt")
        assert result == {"result": "ok"}

    def test_call_does_not_accept_task_parameter(self):
        gw = GeminiGateway()
        with pytest.raises(TypeError):
            gw.call("prompt", task="INBOX_CLASSIFY")

    def test_call_with_markdown_fenced_json(self):
        _setup_genai_response('```json\n{"key": "value"}\n```')
        gw = GeminiGateway()
        result = gw.call("prompt")
        assert result == {"key": "value"}

    def test_call_with_embedded_json(self):
        _setup_genai_response('Some text {"key": "value"} more text')
        gw = GeminiGateway()
        result = gw.call("prompt")
        assert result == {"key": "value"}

    def test_call_with_no_json_returns_raw_parsed(self):
        _setup_genai_response("plain text response")
        gw = GeminiGateway()
        result = gw.call("prompt")
        assert result == {"raw_parsed": "plain text response"}
