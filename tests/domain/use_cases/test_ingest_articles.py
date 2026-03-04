from unittest.mock import MagicMock, patch

from backend.domain.use_cases.ingest_articles import IngestArticles


# ===================================================================
#  execute — creates entries
# ===================================================================

class TestIngestCreatesEntries:

    def test_ingest_creates_entries_for_metadata_only(self):
        """Articles without content are stored with title as-is (no LLM call)."""
        memory = MagicMock()
        memory.remember.side_effect = ["id-1", "id-2"]
        gemini = MagicMock()

        ingest = IngestArticles(memory=memory, gemini=gemini)
        articles = [
            {"title": "Author A — 5 публикаций за 2026-02", "url": "republic://authors/A/2026-02"},
            {"title": "Author B — 3 публикаций за 2026-02", "url": "republic://authors/B/2026-02"},
        ]
        result = ingest.execute(articles)

        assert result == ["id-1", "id-2"]
        assert memory.remember.call_count == 2
        # No LLM call since no content
        gemini.call.assert_not_called()

        # Verify first call args
        call_kwargs = memory.remember.call_args_list[0][1]
        assert call_kwargs["text"] == "Author A — 5 публикаций за 2026-02"
        assert call_kwargs["domain"] == "editorial"
        assert call_kwargs["source"] == "article_ingest"
        assert call_kwargs["source_url"] == "republic://authors/A/2026-02"
        assert call_kwargs["tier"] == "specific"

    def test_ingest_with_custom_domain(self):
        memory = MagicMock()
        memory.remember.return_value = "id-1"
        gemini = MagicMock()

        ingest = IngestArticles(memory=memory, gemini=gemini)
        articles = [{"title": "Test", "url": "https://example.com/1"}]
        ingest.execute(articles, domain="custom_domain")

        assert memory.remember.call_args[1]["domain"] == "custom_domain"

    def test_ingest_empty_list(self):
        memory = MagicMock()
        gemini = MagicMock()

        ingest = IngestArticles(memory=memory, gemini=gemini)
        result = ingest.execute([])

        assert result == []
        memory.remember.assert_not_called()


# ===================================================================
#  execute — updates existing by URL
# ===================================================================

class TestIngestUpdatesExistingByUrl:

    def test_ingest_updates_existing_by_url(self):
        """MemoryService.remember() handles URL dedup internally.
        We just verify IngestArticles passes source_url correctly."""
        memory = MagicMock()
        memory.remember.return_value = "existing-id"
        gemini = MagicMock()

        ingest = IngestArticles(memory=memory, gemini=gemini)
        articles = [{"title": "Updated title", "url": "https://example.com/article/1"}]
        result = ingest.execute(articles)

        assert result == ["existing-id"]
        assert memory.remember.call_args[1]["source_url"] == "https://example.com/article/1"


# ===================================================================
#  execute — summarizes via LLM when content is present
# ===================================================================

class TestIngestSummarizesViaLlm:

    def test_ingest_summarizes_via_llm(self):
        """When article has content, LLM summarization is used."""
        memory = MagicMock()
        memory.remember.return_value = "id-summarized"
        gemini = MagicMock()
        gemini.call.return_value = {"summary": "LLM-generated summary"}

        ingest = IngestArticles(memory=memory, gemini=gemini)
        articles = [{
            "title": "Big Article",
            "url": "https://example.com/big",
            "content": "Full text of the article goes here...",
        }]
        result = ingest.execute(articles)

        assert result == ["id-summarized"]
        gemini.call.assert_called_once()
        assert memory.remember.call_args[1]["text"] == "LLM-generated summary"

    def test_ingest_falls_back_to_title_on_bad_llm_response(self):
        """If LLM doesn't return 'summary' key, fall back to article title."""
        memory = MagicMock()
        memory.remember.return_value = "id-fallback"
        gemini = MagicMock()
        gemini.call.return_value = {"raw_parsed": "something unexpected"}

        ingest = IngestArticles(memory=memory, gemini=gemini)
        articles = [{
            "title": "Fallback Article",
            "url": "https://example.com/fallback",
            "content": "Some content here",
        }]
        result = ingest.execute(articles)

        assert result == ["id-fallback"]
        assert memory.remember.call_args[1]["text"] == "Fallback Article"

    def test_ingest_skips_llm_for_empty_content(self):
        """Empty string content should not trigger LLM."""
        memory = MagicMock()
        memory.remember.return_value = "id-no-llm"
        gemini = MagicMock()

        ingest = IngestArticles(memory=memory, gemini=gemini)
        articles = [{"title": "No content", "url": "https://example.com/empty", "content": ""}]
        ingest.execute(articles)

        gemini.call.assert_not_called()
        assert memory.remember.call_args[1]["text"] == "No content"
