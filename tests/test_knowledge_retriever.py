"""Tests for KnowledgeRetriever and _format_entries helper."""

from unittest.mock import patch


# ===================================================================
#  _format_entries — pure function tests
# ===================================================================

@patch("backend.domain.knowledge_retriever.SUBSCRIPTION_SERVICE_URL", "https://test.example.com")
class TestFormatEntries:

    def _fmt(self, entries):
        from backend.domain.knowledge_retriever import _format_entries
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

@patch("backend.domain.knowledge_retriever.SUBSCRIPTION_SERVICE_URL", "https://test.example.com")
@patch("backend.domain.knowledge_retriever.EmbeddingGateway")
@patch("backend.domain.knowledge_retriever.DbGateway")
def _make_retriever(MockDb, MockEmbed):
    from backend.domain.knowledge_retriever import KnowledgeRetriever
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

    @patch("backend.domain.knowledge_retriever.SUBSCRIPTION_SERVICE_URL", "https://test.example.com")
    def test_formats_results(self):
        kr, mock_db, _ = _make_retriever()
        mock_db.get_knowledge_by_tier.return_value = [
            {"title": "Core", "content": "Important stuff"},
        ]

        result = kr.get_core()

        assert result == "## Core\nImportant stuff"


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
            [0.1, 0.2], scope=None, limit=5,
        )

    def test_passes_scope_and_limit(self):
        kr, mock_db, mock_embed = _make_retriever()
        mock_embed.embed_one.return_value = [0.5]
        mock_db.search_knowledge.return_value = []

        kr.retrieve("query", scope="billing", limit=3)

        mock_db.search_knowledge.assert_called_once_with(
            [0.5], scope="billing", limit=3,
        )

    @patch("backend.domain.knowledge_retriever.SUBSCRIPTION_SERVICE_URL", "https://test.example.com")
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
#  retrieve_full_scope
# ===================================================================

class TestRetrieveFullScope:

    def test_calls_db_with_scope(self):
        kr, mock_db, _ = _make_retriever()
        mock_db.get_knowledge_by_scope.return_value = []

        kr.retrieve_full_scope("subscriptions")

        mock_db.get_knowledge_by_scope.assert_called_once_with("subscriptions")

    @patch("backend.domain.knowledge_retriever.SUBSCRIPTION_SERVICE_URL", "https://test.example.com")
    def test_formats_results(self):
        kr, mock_db, _ = _make_retriever()
        mock_db.get_knowledge_by_scope.return_value = [
            {"title": "Plans", "content": "We have plans"},
        ]

        result = kr.retrieve_full_scope("subscriptions")

        assert result == "## Plans\nWe have plans"
