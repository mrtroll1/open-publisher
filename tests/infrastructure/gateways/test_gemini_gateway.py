"""Tests for GeminiGateway.call() — pure LLM wrapper, no DB logging."""

from unittest.mock import MagicMock, patch

import pytest

from backend.infrastructure.gateways.gemini_gateway import GeminiGateway


def _make_mock_client(response_text: str = '{"result": "ok"}'):
    """Create a mock genai Client that returns the given text."""
    mock_response = MagicMock()
    mock_response.text = response_text
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    return mock_client


class TestGeminiGatewayCall:

    @patch("backend.infrastructure.gateways.gemini_gateway.genai")
    def test_call_returns_parsed_json(self, mock_genai):
        mock_genai.Client.return_value = _make_mock_client('{"result": "ok"}')
        gw = GeminiGateway()
        result = gw.call("test prompt", model="gemini-2.5-flash")
        assert result == {"result": "ok"}

    @patch("backend.infrastructure.gateways.gemini_gateway.genai")
    def test_call_uses_default_model(self, mock_genai):
        mock_genai.Client.return_value = _make_mock_client('{"result": "ok"}')
        gw = GeminiGateway(model="gemini-2.5-flash")
        result = gw.call("prompt")
        assert result == {"result": "ok"}

    def test_call_does_not_accept_task_parameter(self):
        gw = GeminiGateway()
        with pytest.raises(TypeError):
            gw.call("prompt", task="INBOX_CLASSIFY")

    @patch("backend.infrastructure.gateways.gemini_gateway.genai")
    def test_call_with_markdown_fenced_json(self, mock_genai):
        mock_genai.Client.return_value = _make_mock_client('```json\n{"key": "value"}\n```')
        gw = GeminiGateway()
        result = gw.call("prompt")
        assert result == {"key": "value"}

    @patch("backend.infrastructure.gateways.gemini_gateway.genai")
    def test_call_with_embedded_json(self, mock_genai):
        mock_genai.Client.return_value = _make_mock_client('Some text {"key": "value"} more text')
        gw = GeminiGateway()
        result = gw.call("prompt")
        assert result == {"key": "value"}

    @patch("backend.infrastructure.gateways.gemini_gateway.genai")
    def test_call_with_no_json_returns_raw_parsed(self, mock_genai):
        mock_genai.Client.return_value = _make_mock_client("plain text response")
        gw = GeminiGateway()
        result = gw.call("prompt")
        assert result == {"raw_parsed": "plain text response"}
