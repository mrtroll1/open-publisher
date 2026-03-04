"""Tests for KnowledgeRetriever and _format_entries helper."""

from unittest.mock import patch


# ===================================================================
#  _format_entries — pure function tests
# ===================================================================

@patch("backend.domain.services.knowledge_retriever.SUBSCRIPTION_SERVICE_URL", "https://test.example.com")
class TestFormatEntries:

    def _fmt(self, entries):
        from backend.domain.services.knowledge_retriever import _format_entries
        return _format_entries(entries)

    def test_with_title(self):
        result = self._fmt([{"title": "Title", "content": "Content"}])
        assert result == "## Title\nContent"

    def test_without_title(self):
        result = self._fmt([{"content": "Content"}])
        assert result == "Content"

    def test_empty_title(self):
        result = self._fmt([{"title": "", "content": "Content"}])
        assert result == "Content"

    def test_multiple_entries(self):
        entries = [
            {"title": "A", "content": "One"},
            {"content": "Two"},
        ]
        result = self._fmt(entries)
        assert result == "## A\nOne\n\nTwo"

    def test_subscription_url_replacement(self):
        result = self._fmt([{"content": "Visit {{SUBSCRIPTION_SERVICE_URL}} now"}])
        assert result == "Visit https://test.example.com now"

    def test_empty_list(self):
        result = self._fmt([])
        assert result == ""


# ===================================================================
#  Helper: build a KnowledgeRetriever with mocked gateways
# ===================================================================

@patch("backend.domain.services.knowledge_retriever.SUBSCRIPTION_SERVICE_URL", "https://test.example.com")
@patch("backend.domain.services.knowledge_retriever.EmbeddingGateway")
@patch("backend.domain.services.knowledge_retriever.DbGateway")
def _make_retriever(MockDb, MockEmbed):
    from backend.domain.services.knowledge_retriever import KnowledgeRetriever
    kr = KnowledgeRetriever()
    return kr, kr._db, kr._embed


# ===================================================================
#  get_core
# ===================================================================

class TestGetCore:

    def test_calls_db_with_core_tier(self):
        kr, mock_db, _ = _make_retriever()
        mock_db.get_knowledge_by_tier.return_value = []

        kr.get_core()

        mock_db.get_knowledge_by_tier.assert_called_once_with("core")

    @patch("backend.domain.services.knowledge_retriever.SUBSCRIPTION_SERVICE_URL", "https://test.example.com")
    def test_formats_results(self):
        kr, mock_db, _ = _make_retriever()
        mock_db.get_knowledge_by_tier.return_value = [
            {"title": "Core", "content": "Important stuff"},
        ]

        result = kr.get_core()

        assert result == "## Core\nImportant stuff"


# ===================================================================
#  get_domain_context
# ===================================================================

class TestGetDomainContext:

    def test_calls_db_with_domain(self):
        kr, mock_db, _ = _make_retriever()
        mock_db.get_domain_context.return_value = []

        kr.get_domain_context("tech_support")

        mock_db.get_domain_context.assert_called_once_with("tech_support")

    def test_formats_results(self):
        kr, mock_db, _ = _make_retriever()
        mock_db.get_domain_context.return_value = [
            {"title": "Global", "content": "identity stuff"},
            {"title": "Domain", "content": "tech meta"},
        ]

        result = kr.get_domain_context("tech_support")

        assert "## Global\nidentity stuff" in result
        assert "## Domain\ntech meta" in result


# ===================================================================
#  retrieve
# ===================================================================

class TestRetrieve:

    def test_embeds_query(self):
        kr, mock_db, mock_embed = _make_retriever()
        mock_embed.embed_one.return_value = [0.1, 0.2]
        mock_db.search_knowledge.return_value = []

        kr.retrieve("how to cancel?")

        mock_embed.embed_one.assert_called_once_with("how to cancel?")

    def test_calls_search_with_embedding(self):
        kr, mock_db, mock_embed = _make_retriever()
        mock_embed.embed_one.return_value = [0.1, 0.2]
        mock_db.search_knowledge.return_value = []

        kr.retrieve("how to cancel?")

        mock_db.search_knowledge.assert_called_once_with(
            [0.1, 0.2], domain=None, limit=5,
        )

    def test_passes_domain_and_limit(self):
        kr, mock_db, mock_embed = _make_retriever()
        mock_embed.embed_one.return_value = [0.5]
        mock_db.search_knowledge.return_value = []

        kr.retrieve("query", domain="billing", limit=3)

        mock_db.search_knowledge.assert_called_once_with(
            [0.5], domain="billing", limit=3,
        )

    @patch("backend.domain.services.knowledge_retriever.SUBSCRIPTION_SERVICE_URL", "https://test.example.com")
    def test_formats_results(self):
        kr, mock_db, mock_embed = _make_retriever()
        mock_embed.embed_one.return_value = [0.1]
        mock_db.search_knowledge.return_value = [
            {"title": "Billing", "content": "Info about billing"},
            {"content": "Extra detail"},
        ]

        result = kr.retrieve("billing question")

        assert result == "## Billing\nInfo about billing\n\nExtra detail"


# ===================================================================
#  get_multi_domain_context
# ===================================================================

class TestGetMultiDomainContext:

    def test_calls_db_with_domains(self):
        kr, mock_db, _ = _make_retriever()
        mock_db.get_multi_domain_context.return_value = []

        kr.get_multi_domain_context(["tech_support", "editorial"])

        mock_db.get_multi_domain_context.assert_called_once_with(["tech_support", "editorial"])

    def test_formats_results(self):
        kr, mock_db, _ = _make_retriever()
        mock_db.get_multi_domain_context.return_value = [
            {"title": "Global", "content": "identity stuff"},
            {"title": "Tech", "content": "tech meta"},
            {"title": "Edit", "content": "editorial meta"},
        ]

        result = kr.get_multi_domain_context(["tech_support", "editorial"])

        assert "## Global\nidentity stuff" in result
        assert "## Tech\ntech meta" in result
        assert "## Edit\neditorial meta" in result


# ===================================================================
#  retrieve with domains list
# ===================================================================

class TestRetrieveWithDomainsList:

    def test_uses_multi_domain_search(self):
        kr, mock_db, mock_embed = _make_retriever()
        mock_embed.embed_one.return_value = [0.1, 0.2]
        mock_db.search_knowledge_multi_domain.return_value = []

        kr.retrieve("query", domains=["editorial", "payments"])

        mock_db.search_knowledge_multi_domain.assert_called_once_with(
            [0.1, 0.2], domains=["editorial", "payments"], limit=5,
        )
        mock_db.search_knowledge.assert_not_called()

    def test_domain_singular_still_works(self):
        kr, mock_db, mock_embed = _make_retriever()
        mock_embed.embed_one.return_value = [0.5]
        mock_db.search_knowledge.return_value = []

        kr.retrieve("query", domain="billing", limit=3)

        mock_db.search_knowledge.assert_called_once_with(
            [0.5], domain="billing", limit=3,
        )
        mock_db.search_knowledge_multi_domain.assert_not_called()

    @patch("backend.domain.services.knowledge_retriever.SUBSCRIPTION_SERVICE_URL", "https://test.example.com")
    def test_formats_results(self):
        kr, mock_db, mock_embed = _make_retriever()
        mock_embed.embed_one.return_value = [0.1]
        mock_db.search_knowledge_multi_domain.return_value = [
            {"title": "A", "content": "From editorial"},
            {"title": "B", "content": "From payments"},
        ]

        result = kr.retrieve("multi query", domains=["editorial", "payments"])

        assert "## A\nFrom editorial" in result
        assert "## B\nFrom payments" in result


# ===================================================================
#  retrieve_full_domain
# ===================================================================

class TestRetrieveFullDomain:

    def test_calls_db_with_domain(self):
        kr, mock_db, _ = _make_retriever()
        mock_db.get_knowledge_by_domain.return_value = []

        kr.retrieve_full_domain("subscriptions")

        mock_db.get_knowledge_by_domain.assert_called_once_with("subscriptions")

    @patch("backend.domain.services.knowledge_retriever.SUBSCRIPTION_SERVICE_URL", "https://test.example.com")
    def test_formats_results(self):
        kr, mock_db, _ = _make_retriever()
        mock_db.get_knowledge_by_domain.return_value = [
            {"title": "Plans", "content": "We have plans"},
        ]

        result = kr.retrieve_full_domain("subscriptions")

        assert result == "## Plans\nWe have plans"


# ===================================================================
#  store_feedback
# ===================================================================

class TestStoreFeedback:

    def test_happy_path(self):
        kr, mock_db, mock_embed = _make_retriever()
        mock_embed.embed_one.return_value = [0.1, 0.2, 0.3]
        mock_db.search_knowledge.return_value = []
        mock_db.save_knowledge_entry.return_value = "new-uuid-123"

        result = kr.store_feedback("Don't reply to spam", domain="tech_support")

        assert result == "new-uuid-123"
        mock_embed.embed_one.assert_called_once_with("Don't reply to spam")
        mock_db.save_knowledge_entry.assert_called_once_with(
            tier="specific",
            domain="tech_support",
            title="Don't reply to spam",
            content="Don't reply to spam",
            source="admin_feedback",
            embedding=[0.1, 0.2, 0.3],
        )

    def test_title_truncated_at_60_chars(self):
        kr, mock_db, mock_embed = _make_retriever()
        mock_embed.embed_one.return_value = [0.5]
        mock_db.search_knowledge.return_value = []
        mock_db.save_knowledge_entry.return_value = "uuid"

        long_text = "A" * 100
        kr.store_feedback(long_text, domain="tech_support")

        call_kwargs = mock_db.save_knowledge_entry.call_args[1]
        assert len(call_kwargs["title"]) == 60
        assert call_kwargs["content"] == long_text

    def test_deduplicates_similar(self):
        kr, mock_db, mock_embed = _make_retriever()
        mock_embed.embed_one.return_value = [0.1, 0.2]
        mock_db.search_knowledge.return_value = [
            {"id": "existing-id", "similarity": 0.95},
        ]

        result = kr.store_feedback("Updated feedback", domain="tech_support")

        assert result == "existing-id"
        mock_db.update_knowledge_entry.assert_called_once_with(
            "existing-id", "Updated feedback", [0.1, 0.2],
        )
        mock_db.save_knowledge_entry.assert_not_called()

    def test_creates_new_when_different(self):
        kr, mock_db, mock_embed = _make_retriever()
        mock_embed.embed_one.return_value = [0.1, 0.2]
        mock_db.search_knowledge.return_value = [
            {"id": "other-id", "similarity": 0.50},
        ]
        mock_db.save_knowledge_entry.return_value = "new-id"

        result = kr.store_feedback("Brand new feedback", domain="tech_support")

        assert result == "new-id"
        mock_db.update_knowledge_entry.assert_not_called()
        mock_db.save_knowledge_entry.assert_called_once()


# ===================================================================
#  store_teaching
# ===================================================================

class TestStoreTeaching:

    def test_happy_path(self):
        kr, mock_db, mock_embed = _make_retriever()
        mock_embed.embed_one.return_value = [0.4, 0.5]
        mock_db.search_knowledge.return_value = []
        mock_db.save_knowledge_entry.return_value = "teach-uuid"

        result = kr.store_teaching("Always greet in Russian", domain="general", tier="meta")

        assert result == "teach-uuid"
        mock_db.save_knowledge_entry.assert_called_once_with(
            tier="meta",
            domain="general",
            title="Always greet in Russian",
            content="Always greet in Russian",
            source="admin_teach",
            embedding=[0.4, 0.5],
        )

    def test_deduplicates_similar(self):
        kr, mock_db, mock_embed = _make_retriever()
        mock_embed.embed_one.return_value = [0.3]
        mock_db.search_knowledge.return_value = [
            {"id": "old-teaching-id", "similarity": 0.92},
        ]

        result = kr.store_teaching("Updated teaching", domain="general")

        assert result == "old-teaching-id"
        mock_db.update_knowledge_entry.assert_called_once_with(
            "old-teaching-id", "Updated teaching", [0.3],
        )
        mock_db.save_knowledge_entry.assert_not_called()

    def test_creates_new_when_different(self):
        kr, mock_db, mock_embed = _make_retriever()
        mock_embed.embed_one.return_value = [0.7]
        mock_db.search_knowledge.return_value = [
            {"id": "unrelated-id", "similarity": 0.40},
        ]
        mock_db.save_knowledge_entry.return_value = "new-teach-id"

        result = kr.store_teaching("Completely new topic", domain="payments")

        assert result == "new-teach-id"
        mock_db.update_knowledge_entry.assert_not_called()
        mock_db.save_knowledge_entry.assert_called_once()

    def test_creates_new_when_no_existing(self):
        kr, mock_db, mock_embed = _make_retriever()
        mock_embed.embed_one.return_value = [0.1]
        mock_db.search_knowledge.return_value = []
        mock_db.save_knowledge_entry.return_value = "fresh-id"

        result = kr.store_teaching("First teaching ever")

        assert result == "fresh-id"
        mock_db.save_knowledge_entry.assert_called_once()

    def test_boundary_similarity_090_does_not_dedup(self):
        """Similarity exactly 0.90 should NOT trigger dedup (> 0.90 required)."""
        kr, mock_db, mock_embed = _make_retriever()
        mock_embed.embed_one.return_value = [0.5]
        mock_db.search_knowledge.return_value = [
            {"id": "boundary-id", "similarity": 0.90},
        ]
        mock_db.save_knowledge_entry.return_value = "new-id"

        result = kr.store_teaching("Borderline similar")

        assert result == "new-id"
        mock_db.update_knowledge_entry.assert_not_called()
        mock_db.save_knowledge_entry.assert_called_once()


# ===================================================================
#  get_entity_context
# ===================================================================

class TestGetEntityContext:

    @patch("backend.domain.services.knowledge_retriever.SUBSCRIPTION_SERVICE_URL", "https://test.example.com")
    def test_formats_correctly(self):
        kr, mock_db, _ = _make_retriever()
        mock_db.get_entity.return_value = {
            "id": "e1", "name": "Иван Иванов", "summary": "Автор и редактор",
        }
        mock_db.get_entity_knowledge.return_value = [
            {"title": "Заметка", "content": "Важная информация"},
        ]

        result = kr.get_entity_context("e1")

        assert "## Иван Иванов" in result
        assert "Автор и редактор" in result
        assert "## Заметка" in result
        assert "Важная информация" in result
        mock_db.get_entity.assert_called_once_with("e1")
        mock_db.get_entity_knowledge.assert_called_once_with("e1", limit=5)

    def test_missing_entity_returns_empty(self):
        kr, mock_db, _ = _make_retriever()
        mock_db.get_entity.return_value = None

        result = kr.get_entity_context("nonexistent")

        assert result == ""
        mock_db.get_entity_knowledge.assert_not_called()

    @patch("backend.domain.services.knowledge_retriever.SUBSCRIPTION_SERVICE_URL", "https://test.example.com")
    def test_no_summary_no_entries(self):
        kr, mock_db, _ = _make_retriever()
        mock_db.get_entity.return_value = {
            "id": "e2", "name": "Test", "summary": "",
        }
        mock_db.get_entity_knowledge.return_value = []

        result = kr.get_entity_context("e2")

        assert result == ""

    @patch("backend.domain.services.knowledge_retriever.SUBSCRIPTION_SERVICE_URL", "https://test.example.com")
    def test_summary_only_no_entries(self):
        kr, mock_db, _ = _make_retriever()
        mock_db.get_entity.return_value = {
            "id": "e3", "name": "Alice", "summary": "A developer",
        }
        mock_db.get_entity_knowledge.return_value = []

        result = kr.get_entity_context("e3")

        assert result == "## Alice\nA developer"

    @patch("backend.domain.services.knowledge_retriever.SUBSCRIPTION_SERVICE_URL", "https://test.example.com")
    def test_entries_only_no_summary(self):
        kr, mock_db, _ = _make_retriever()
        mock_db.get_entity.return_value = {
            "id": "e4", "name": "Bob",
        }
        mock_db.get_entity_knowledge.return_value = [
            {"title": "Note", "content": "Something"},
        ]

        result = kr.get_entity_context("e4")

        assert result == "## Note\nSomething"


# ===================================================================
#  store_entity_knowledge
# ===================================================================

class TestStoreEntityKnowledge:

    def test_happy_path(self):
        kr, mock_db, mock_embed = _make_retriever()
        mock_embed.embed_one.return_value = [0.1, 0.2, 0.3]
        mock_db.search_knowledge.return_value = []
        mock_db.save_knowledge_entry.return_value = "new-entity-kb-id"

        result = kr.store_entity_knowledge("entity-1", "Entity specific info", domain="editorial")

        assert result == "new-entity-kb-id"
        mock_embed.embed_one.assert_called_once_with("Entity specific info")
        mock_db.save_knowledge_entry.assert_called_once_with(
            tier="specific",
            domain="editorial",
            title="Entity specific info",
            content="Entity specific info",
            source="admin_teach",
            embedding=[0.1, 0.2, 0.3],
            entity_id="entity-1",
        )

    def test_deduplicates_similar(self):
        kr, mock_db, mock_embed = _make_retriever()
        mock_embed.embed_one.return_value = [0.4, 0.5]
        mock_db.search_knowledge.return_value = [
            {"id": "existing-id", "similarity": 0.95},
        ]

        result = kr.store_entity_knowledge("entity-1", "Updated info")

        assert result == "existing-id"
        mock_db.update_knowledge_entry.assert_called_once_with(
            "existing-id", "Updated info", [0.4, 0.5],
        )
        mock_db.save_knowledge_entry.assert_not_called()

    def test_creates_new_when_different(self):
        kr, mock_db, mock_embed = _make_retriever()
        mock_embed.embed_one.return_value = [0.7]
        mock_db.search_knowledge.return_value = [
            {"id": "other-id", "similarity": 0.40},
        ]
        mock_db.save_knowledge_entry.return_value = "new-id"

        result = kr.store_entity_knowledge("entity-2", "Completely new info")

        assert result == "new-id"
        mock_db.update_knowledge_entry.assert_not_called()
        mock_db.save_knowledge_entry.assert_called_once()

    def test_default_domain_is_general(self):
        kr, mock_db, mock_embed = _make_retriever()
        mock_embed.embed_one.return_value = [0.1]
        mock_db.search_knowledge.return_value = []
        mock_db.save_knowledge_entry.return_value = "id"

        kr.store_entity_knowledge("entity-1", "Some text")

        call_kwargs = mock_db.save_knowledge_entry.call_args[1]
        assert call_kwargs["domain"] == "general"

    def test_title_truncated_at_60_chars(self):
        kr, mock_db, mock_embed = _make_retriever()
        mock_embed.embed_one.return_value = [0.5]
        mock_db.search_knowledge.return_value = []
        mock_db.save_knowledge_entry.return_value = "id"

        long_text = "A" * 100
        kr.store_entity_knowledge("entity-1", long_text)

        call_kwargs = mock_db.save_knowledge_entry.call_args[1]
        assert len(call_kwargs["title"]) == 60
        assert call_kwargs["content"] == long_text
