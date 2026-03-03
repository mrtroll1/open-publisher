"""Tests for EmbeddingGateway."""

import sys
from unittest.mock import MagicMock, patch

import pytest

from backend.infrastructure.gateways.embedding_gateway import EmbeddingGateway

_mock_genai = MagicMock()


@pytest.fixture(autouse=True)
def _patch_genai():
    """Ensure our mock is active in sys.modules for each test."""
    _mock_genai.reset_mock()
    with patch.dict(sys.modules, {"google.genai": _mock_genai, "google.genai.types": _mock_genai.types}):
        yield


def _make_embedding(values: list[float]):
    e = MagicMock()
    e.values = values
    return e


def _setup_embed_response(embeddings: list[list[float]]):
    mock_response = MagicMock()
    mock_response.embeddings = [_make_embedding(v) for v in embeddings]
    mock_client = MagicMock()
    mock_client.models.embed_content.return_value = mock_response
    _mock_genai.Client.return_value = mock_client
    return mock_client


class TestEmbedOne:

    def test_returns_list_of_floats_with_correct_length(self):
        vector = [0.1] * 256
        _setup_embed_response([vector])

        gw = EmbeddingGateway()
        result = gw.embed_one("hello")

        assert isinstance(result, list)
        assert len(result) == 256
        assert all(isinstance(v, float) for v in result)

    def test_passes_correct_model_and_dimensionality(self):
        vector = [0.0] * 256
        mock_client = _setup_embed_response([vector])

        gw = EmbeddingGateway()
        gw.embed_one("test")

        call_kwargs = mock_client.models.embed_content.call_args
        assert call_kwargs.kwargs["model"] == "gemini-embedding-001"
        # Verify EmbedContentConfig was constructed with correct dimensionality
        _mock_genai.types.EmbedContentConfig.assert_called_with(output_dimensionality=256)


class TestEmbedTexts:

    def test_returns_correct_number_of_embeddings(self):
        vectors = [[0.1] * 256, [0.2] * 256, [0.3] * 256]
        _setup_embed_response(vectors)

        gw = EmbeddingGateway()
        result = gw.embed_texts(["a", "b", "c"])

        assert len(result) == 3
        assert all(len(v) == 256 for v in result)

    def test_passes_all_texts_to_api(self):
        vectors = [[0.0] * 256, [0.0] * 256]
        mock_client = _setup_embed_response(vectors)

        gw = EmbeddingGateway()
        gw.embed_texts(["first", "second"])

        call_kwargs = mock_client.models.embed_content.call_args
        assert call_kwargs.kwargs["contents"] == ["first", "second"]

    def test_custom_model_and_dimensions(self):
        mock_client = _setup_embed_response([[0.0] * 128])

        gw = EmbeddingGateway(model="custom-model", dimensions=128)
        gw.embed_texts(["x"])

        call_kwargs = mock_client.models.embed_content.call_args
        assert call_kwargs.kwargs["model"] == "custom-model"
        _mock_genai.types.EmbedContentConfig.assert_called_with(output_dimensionality=128)
