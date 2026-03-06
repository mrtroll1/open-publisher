"""Embedding gateway — Google gemini-embedding-001 wrapper."""

from __future__ import annotations

from backend.config import GEMINI_API_KEY


class EmbeddingGateway:

    def __init__(self, model: str = "gemini-embedding-001", dimensions: int = 256):
        self._model = model
        self._dimensions = dimensions

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.embed_content(
            model=self._model,
            contents=texts,
            config=types.EmbedContentConfig(output_dimensionality=self._dimensions),
        )
        return [e.values for e in response.embeddings]

    def embed_one(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]
