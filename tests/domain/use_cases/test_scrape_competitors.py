from datetime import timedelta
from unittest.mock import MagicMock, call

from backend.domain.use_cases.scrape_competitors import ScrapeCompetitors


def _mock_retriever():
    r = MagicMock()
    r.get_core.return_value = ""
    return r


# ===================================================================
#  execute — creates entity and knowledge entry
# ===================================================================

class TestScrapeCreatesEntityAndKnowledge:

    def test_scrape_creates_entity_and_knowledge(self):
        """When entity doesn't exist, creates it and stores knowledge."""
        memory = MagicMock()
        memory.find_entity.return_value = None
        memory.add_entity.return_value = "entity-new"
        memory.remember.return_value = "entry-1"
        gemini = MagicMock()
        gemini.call.return_value = {"summary": "Competitor analysis summary"}

        scraper = ScrapeCompetitors(memory=memory, gemini=gemini, retriever=_mock_retriever())
        sources = [{
            "name": "Meduza",
            "url": "https://meduza.io",
            "content": "Latest news from Meduza...",
        }]
        result = scraper.execute(sources)

        assert result == ["entry-1"]
        memory.add_domain.assert_called_once_with("competitors", "Наблюдения за конкурентами")
        memory.find_entity.assert_called_once_with(query="Meduza")
        memory.add_entity.assert_called_once_with(kind="competitor", name="Meduza")
        memory.remember.assert_called_once()
        call_kwargs = memory.remember.call_args[1]
        assert call_kwargs["text"] == "Competitor analysis summary"
        assert call_kwargs["domain"] == "competitors"
        assert call_kwargs["source"] == "competitor_scraper"
        assert call_kwargs["source_url"] == "https://meduza.io"
        assert call_kwargs["entity_id"] == "entity-new"
        assert call_kwargs["tier"] == "specific"


# ===================================================================
#  execute — reuses existing entity
# ===================================================================

class TestScrapeReusesExistingEntity:

    def test_scrape_reuses_existing_entity(self):
        """When entity already exists, uses its ID without creating a new one."""
        memory = MagicMock()
        memory.find_entity.return_value = {"id": "entity-existing", "name": "Meduza"}
        memory.remember.return_value = "entry-2"
        gemini = MagicMock()
        gemini.call.return_value = {"summary": "Updated analysis"}

        scraper = ScrapeCompetitors(memory=memory, gemini=gemini, retriever=_mock_retriever())
        sources = [{
            "name": "Meduza",
            "url": "https://meduza.io/2026",
            "content": "New content from Meduza...",
        }]
        result = scraper.execute(sources)

        assert result == ["entry-2"]
        memory.add_entity.assert_not_called()
        assert memory.remember.call_args[1]["entity_id"] == "entity-existing"

    def test_scrape_multiple_sources_mixed(self):
        """Mix of new and existing entities."""
        memory = MagicMock()
        memory.find_entity.side_effect = [
            None,
            {"id": "entity-existing", "name": "The Bell"},
        ]
        memory.add_entity.return_value = "entity-new"
        memory.remember.side_effect = ["entry-1", "entry-2"]
        gemini = MagicMock()
        gemini.call.return_value = {"summary": "Analysis"}

        scraper = ScrapeCompetitors(memory=memory, gemini=gemini, retriever=_mock_retriever())
        sources = [
            {"name": "Meduza", "url": "https://meduza.io", "content": "Content A"},
            {"name": "The Bell", "url": "https://thebell.io", "content": "Content B"},
        ]
        result = scraper.execute(sources)

        assert result == ["entry-1", "entry-2"]
        memory.add_entity.assert_called_once_with(kind="competitor", name="Meduza")
        assert memory.remember.call_count == 2


# ===================================================================
#  execute — updates by source URL
# ===================================================================

class TestScrapeUpdatesBySourceUrl:

    def test_scrape_updates_by_source_url(self):
        """MemoryService.remember() handles URL dedup internally.
        We verify source_url is passed correctly."""
        memory = MagicMock()
        memory.find_entity.return_value = {"id": "entity-1", "name": "Meduza"}
        memory.remember.return_value = "entry-updated"
        gemini = MagicMock()
        gemini.call.return_value = {"summary": "Updated summary"}

        scraper = ScrapeCompetitors(memory=memory, gemini=gemini, retriever=_mock_retriever())
        sources = [{
            "name": "Meduza",
            "url": "https://meduza.io/specific-page",
            "content": "Updated content",
        }]
        result = scraper.execute(sources)

        assert result == ["entry-updated"]
        assert memory.remember.call_args[1]["source_url"] == "https://meduza.io/specific-page"

    def test_scrape_empty_sources(self):
        memory = MagicMock()
        gemini = MagicMock()

        scraper = ScrapeCompetitors(memory=memory, gemini=gemini, retriever=_mock_retriever())
        result = scraper.execute([])

        assert result == []
        memory.remember.assert_not_called()
        memory.find_entity.assert_not_called()

    def test_scrape_falls_back_on_bad_llm_response(self):
        """If LLM doesn't return 'summary', fallback to name: url."""
        memory = MagicMock()
        memory.find_entity.return_value = None
        memory.add_entity.return_value = "entity-1"
        memory.remember.return_value = "entry-fallback"
        gemini = MagicMock()
        gemini.call.return_value = {"raw_parsed": "unexpected"}

        scraper = ScrapeCompetitors(memory=memory, gemini=gemini, retriever=_mock_retriever())
        sources = [{
            "name": "Novaya",
            "url": "https://novayagazeta.eu",
            "content": "Some content",
        }]
        result = scraper.execute(sources)

        assert result == ["entry-fallback"]
        assert memory.remember.call_args[1]["text"] == "Novaya: https://novayagazeta.eu"


# ===================================================================
#  execute — expires_at is set to 90 days
# ===================================================================

class TestScrapeExpiresAt:

    def test_scrape_sets_90_day_expiry(self):
        """Competitor summaries should expire after 90 days."""
        memory = MagicMock()
        memory.find_entity.return_value = {"id": "entity-1", "name": "Meduza"}
        memory.remember.return_value = "entry-1"
        gemini = MagicMock()
        gemini.call.return_value = {"summary": "Analysis"}

        scraper = ScrapeCompetitors(memory=memory, gemini=gemini, retriever=_mock_retriever())
        sources = [{
            "name": "Meduza",
            "url": "https://meduza.io",
            "content": "Content",
        }]
        scraper.execute(sources)

        expires_at = memory.remember.call_args[1]["expires_at"]
        assert expires_at is not None
        from datetime import datetime
        delta = expires_at - datetime.utcnow()
        assert timedelta(days=89) <= delta <= timedelta(days=91)
