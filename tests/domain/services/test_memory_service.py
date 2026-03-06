"""Tests for MemoryService."""

from unittest.mock import MagicMock, patch


def _make_service():
    from backend.infrastructure.memory.memory_service import MemoryService
    mock_db = MagicMock()
    mock_embed = MagicMock()
    mock_retriever = MagicMock()
    svc = MemoryService(db=mock_db, embed=mock_embed,
                        retriever=mock_retriever)
    return svc, mock_db, mock_embed, mock_retriever


# ===================================================================
#  remember
# ===================================================================

class TestRemember:

    def test_stores_and_returns_id(self):
        svc, mock_db, mock_embed, _ = _make_service()
        mock_embed.embed_one.return_value = [0.1, 0.2, 0.3]
        mock_db.search_knowledge.return_value = []
        mock_db.save_knowledge_entry.return_value = "new-uuid-123"

        result = svc.remember("Important fact", domain="general")

        assert result == "new-uuid-123"
        mock_embed.embed_one.assert_called_once_with("Important fact")
        mock_db.save_knowledge_entry.assert_called_once_with(
            tier="specific", domain="general", title="Important fact",
            content="Important fact", source="api",
            embedding=[0.1, 0.2, 0.3], entity_id=None,
            source_url=None, expires_at=None,
        )

    def test_deduplicates(self):
        svc, mock_db, mock_embed, _ = _make_service()
        mock_embed.embed_one.return_value = [0.4, 0.5]
        mock_db.search_knowledge.return_value = [
            {"id": "existing-id", "similarity": 0.95},
        ]

        result = svc.remember("Updated fact", domain="general")

        assert result == "existing-id"
        mock_db.update_knowledge_entry.assert_called_once_with(
            "existing-id", "Updated fact", [0.4, 0.5],
        )
        mock_db.save_knowledge_entry.assert_not_called()

    def test_no_dedup_below_threshold(self):
        svc, mock_db, mock_embed, _ = _make_service()
        mock_embed.embed_one.return_value = [0.1]
        mock_db.search_knowledge.return_value = [
            {"id": "other-id", "similarity": 0.89},
        ]
        mock_db.save_knowledge_entry.return_value = "new-id"

        result = svc.remember("Different fact", domain="general")

        assert result == "new-id"
        mock_db.update_knowledge_entry.assert_not_called()

    def test_passes_optional_fields(self):
        from datetime import datetime
        svc, mock_db, mock_embed, _ = _make_service()
        mock_embed.embed_one.return_value = [0.1]
        mock_db.find_by_source_url.return_value = None
        mock_db.search_knowledge.return_value = []
        mock_db.save_knowledge_entry.return_value = "id"
        exp = datetime(2026, 12, 31)

        svc.remember("Fact", domain="billing", source="import",
                     tier="meta", entity_id="e1",
                     source_url="https://example.com", expires_at=exp)

        call_kwargs = mock_db.save_knowledge_entry.call_args[1]
        assert call_kwargs["source"] == "import"
        assert call_kwargs["tier"] == "meta"
        assert call_kwargs["entity_id"] == "e1"
        assert call_kwargs["source_url"] == "https://example.com"
        assert call_kwargs["expires_at"] == exp

    def test_remember_with_source_url_deduplicates(self):
        svc, mock_db, mock_embed, _ = _make_service()
        mock_embed.embed_one.return_value = [0.1, 0.2]
        mock_db.find_by_source_url.return_value = {"id": "url-existing-id"}

        result = svc.remember("New content", domain="general",
                              source_url="https://example.com/page")

        assert result == "url-existing-id"
        mock_db.find_by_source_url.assert_called_once_with("https://example.com/page")
        mock_db.update_knowledge_entry.assert_called_once_with(
            "url-existing-id", "New content", [0.1, 0.2],
        )
        mock_db.save_knowledge_entry.assert_not_called()
        # Embedding dedup should be skipped when URL dedup hits
        mock_db.search_knowledge.assert_not_called()

    def test_remember_source_url_updates_content(self):
        svc, mock_db, mock_embed, _ = _make_service()
        mock_embed.embed_one.return_value = [0.3, 0.4]
        mock_db.find_by_source_url.return_value = {"id": "page-id"}

        svc.remember("Updated page content", domain="editorial",
                     source_url="https://example.com/article")

        mock_db.update_knowledge_entry.assert_called_once_with(
            "page-id", "Updated page content", [0.3, 0.4],
        )

    def test_remember_different_urls_creates_separate(self):
        svc, mock_db, mock_embed, _ = _make_service()
        mock_embed.embed_one.return_value = [0.5]
        mock_db.find_by_source_url.return_value = None
        mock_db.search_knowledge.return_value = []
        mock_db.save_knowledge_entry.return_value = "new-id"

        result = svc.remember("Content A", domain="general",
                              source_url="https://example.com/new-page")

        assert result == "new-id"
        mock_db.find_by_source_url.assert_called_once_with("https://example.com/new-page")
        mock_db.save_knowledge_entry.assert_called_once()


# ===================================================================
#  recall
# ===================================================================

class TestRecall:

    def test_returns_relevant(self):
        svc, mock_db, mock_embed, _ = _make_service()
        mock_embed.embed_one.return_value = [0.1, 0.2]
        mock_db.search_knowledge.return_value = [
            {"id": "1", "title": "Billing", "content": "Info", "similarity": 0.85, "domain": "billing"},
            {"id": "2", "title": "Support", "content": "Help", "similarity": 0.75, "domain": "support"},
        ]

        results = svc.recall("billing question")

        assert len(results) == 2
        assert results[0]["id"] == "1"
        assert results[0]["title"] == "Billing"
        assert results[0]["content"] == "Info"
        assert results[0]["similarity"] == 0.85
        assert results[0]["domain"] == "billing"

    def test_with_domain_filter(self):
        svc, mock_db, mock_embed, _ = _make_service()
        mock_embed.embed_one.return_value = [0.5]
        mock_db.search_knowledge.return_value = [
            {"id": "3", "title": "T", "content": "C", "similarity": 0.9, "domain": "billing"},
        ]

        results = svc.recall("query", domain="billing")

        mock_db.search_knowledge.assert_called_once_with([0.5], domain="billing", limit=5)
        assert len(results) == 1

    def test_with_multi_domain(self):
        svc, mock_db, mock_embed, _ = _make_service()
        mock_embed.embed_one.return_value = [0.5]
        mock_db.search_knowledge_multi_domain.return_value = []

        svc.recall("query", domains=["billing", "support"])

        mock_db.search_knowledge_multi_domain.assert_called_once_with(
            [0.5], domains=["billing", "support"], limit=5,
        )
        mock_db.search_knowledge.assert_not_called()


# ===================================================================
#  teach
# ===================================================================

class TestTeach:

    def test_delegates_to_retriever(self):
        svc, _, _, mock_retriever = _make_service()
        mock_retriever.store_teaching.return_value = "teach-id"

        result = svc.teach("Always greet users in Russian",
                           domain="tech_support", tier="meta")

        assert result == "teach-id"
        mock_retriever.store_teaching.assert_called_once_with(
            "Always greet users in Russian", domain="tech_support", tier="meta",
        )

    def test_passes_domain_and_tier(self):
        svc, _, _, mock_retriever = _make_service()
        mock_retriever.store_teaching.return_value = "id"

        svc.teach("Some fact", domain="billing", tier="specific")

        mock_retriever.store_teaching.assert_called_once_with(
            "Some fact", domain="billing", tier="specific",
        )


# ===================================================================
#  get_context
# ===================================================================

class TestGetContext:

    def test_assembles_all_layers(self):
        svc, mock_db, _, mock_retriever = _make_service()
        mock_db.get_environment.return_value = {
            "name": "prod", "system_context": "You are a helper.",
            "allowed_domains": ["billing", "support"],
        }
        mock_retriever.get_multi_domain_context.return_value = "core knowledge"
        mock_retriever.retrieve.return_value = "relevant stuff"

        result = svc.get_context(environment="prod", query="billing question")

        assert result["environment"] == "You are a helper."
        assert result["domains"] == ["billing", "support"]
        assert "core knowledge" in result["knowledge"]
        assert "relevant stuff" in result["knowledge"]

    def test_with_entity(self):
        svc, mock_db, _, mock_retriever = _make_service()
        mock_db.get_environment_by_chat_id.return_value = None
        mock_db.find_entity_by_external_id.return_value = {"id": "e1", "name": "User"}
        mock_retriever.get_core.return_value = "core"
        mock_retriever.get_entity_context.return_value = "## User\nImportant user info"

        result = svc.get_context(user_id=12345)

        assert result["user_context"] == "## User\nImportant user info"
        mock_db.find_entity_by_external_id.assert_called_once_with("telegram_user_id", 12345)
        mock_retriever.get_entity_context.assert_called_once_with("e1")

    def test_by_chat_id(self):
        svc, mock_db, _, mock_retriever = _make_service()
        mock_db.get_environment_by_chat_id.return_value = {
            "name": "dev", "system_context": "Dev context",
            "allowed_domains": ["dev"],
        }
        mock_retriever.get_multi_domain_context.return_value = "dev knowledge"

        result = svc.get_context(chat_id=99999)

        assert result["environment"] == "Dev context"
        assert result["domains"] == ["dev"]

    def test_no_environment(self):
        svc, mock_db, _, mock_retriever = _make_service()
        mock_retriever.get_core.return_value = "global core"
        mock_retriever.retrieve.return_value = "relevant"

        result = svc.get_context(query="something")

        assert result["environment"] == ""
        assert result["domains"] == []
        assert "global core" in result["knowledge"]

    def test_no_query_only_core(self):
        svc, mock_db, _, mock_retriever = _make_service()
        mock_retriever.get_core.return_value = "core only"

        result = svc.get_context()

        assert result["knowledge"] == "core only"
        mock_retriever.retrieve.assert_not_called()


# ===================================================================
#  entity CRUD
# ===================================================================

class TestEntityOps:

    def test_add_entity(self):
        svc, mock_db, mock_embed, _ = _make_service()
        mock_embed.embed_one.return_value = [0.1, 0.2]
        mock_db.save_entity.return_value = "entity-uuid"

        result = svc.add_entity("person", "John Doe", summary="A developer")

        assert result == "entity-uuid"
        mock_embed.embed_one.assert_called_once_with("John Doe")
        mock_db.save_entity.assert_called_once_with(
            "person", "John Doe", external_ids=None,
            summary="A developer", embedding=[0.1, 0.2],
        )

    def test_find_entity_by_external_id(self):
        svc, mock_db, _, _ = _make_service()
        mock_db.find_entity_by_external_id.return_value = {
            "id": "e1", "name": "John",
        }

        result = svc.find_entity(external_key="telegram_user_id", external_value="123")

        assert result["id"] == "e1"
        mock_db.find_entity_by_external_id.assert_called_once_with("telegram_user_id", "123")

    def test_find_entity_by_name(self):
        svc, mock_db, _, _ = _make_service()
        mock_db.find_entities_by_name.return_value = [
            {"id": "e2", "name": "Alice"},
        ]

        result = svc.find_entity(query="Alice")

        assert result["id"] == "e2"
        mock_db.find_entities_by_name.assert_called_once_with("Alice", limit=1)

    def test_find_entity_not_found(self):
        svc, mock_db, _, _ = _make_service()
        mock_db.find_entities_by_name.return_value = []

        result = svc.find_entity(query="Nobody")

        assert result is None

    def test_find_entity_no_params(self):
        svc, _, _, _ = _make_service()

        result = svc.find_entity()

        assert result is None

    def test_update_entity_summary(self):
        svc, mock_db, mock_embed, _ = _make_service()
        mock_embed.embed_one.return_value = [0.3, 0.4]
        mock_db.update_entity.return_value = True

        result = svc.update_entity_summary("e1", "Updated summary")

        assert result is True
        mock_embed.embed_one.assert_called_once_with("Updated summary")
        mock_db.update_entity.assert_called_once_with(
            "e1", summary="Updated summary", embedding=[0.3, 0.4],
        )


# ===================================================================
#  environment ops
# ===================================================================

class TestEnvironmentOps:

    def test_lookup_by_chat_id(self):
        svc, mock_db, _, _ = _make_service()
        mock_db.get_environment_by_chat_id.return_value = {
            "name": "prod", "description": "Production",
            "system_context": "ctx", "allowed_domains": ["billing"],
        }

        result = svc.get_environment(chat_id=12345)

        assert result["name"] == "prod"
        mock_db.get_environment_by_chat_id.assert_called_once_with(12345)

    def test_lookup_by_name(self):
        svc, mock_db, _, _ = _make_service()
        mock_db.get_environment.return_value = {
            "name": "staging", "description": "Staging env",
        }

        result = svc.get_environment(name="staging")

        assert result["name"] == "staging"
        mock_db.get_environment.assert_called_once_with("staging")

    def test_list_environments(self):
        svc, mock_db, _, _ = _make_service()
        mock_db.list_environments.return_value = [
            {"name": "prod"}, {"name": "staging"},
        ]

        result = svc.list_environments()

        assert len(result) == 2

    def test_update_environment(self):
        svc, mock_db, _, _ = _make_service()
        mock_db.update_environment.return_value = True

        result = svc.update_environment("prod", description="Updated")

        assert result is True
        mock_db.update_environment.assert_called_once_with("prod", description="Updated")


# ===================================================================
#  domain ops
# ===================================================================

class TestDomainOps:

    def test_list_domains(self):
        svc, mock_db, _, _ = _make_service()
        mock_db.list_domains.return_value = [
            {"name": "general", "description": "General"},
        ]

        result = svc.list_domains()

        assert len(result) == 1

    def test_add_domain(self):
        svc, mock_db, _, _ = _make_service()
        mock_db.get_or_create_domain.return_value = "billing"

        result = svc.add_domain("billing", "Billing domain")

        assert result == "billing"
        mock_db.get_or_create_domain.assert_called_once_with("billing", "Billing domain")


# ===================================================================
#  knowledge management
# ===================================================================

class TestKnowledgeManagement:

    def test_list_knowledge(self):
        svc, mock_db, _, _ = _make_service()
        mock_db.list_knowledge.return_value = [
            {"id": "1", "tier": "core", "domain": "general", "title": "T", "content": "C"},
        ]

        result = svc.list_knowledge(domain="general")

        assert len(result) == 1
        mock_db.list_knowledge.assert_called_once_with(domain="general", tier=None)

    def test_list_knowledge_by_entity(self):
        svc, mock_db, _, _ = _make_service()
        mock_db.get_entity_knowledge.return_value = [
            {"id": "2", "content": "Entity note"},
        ]

        result = svc.list_knowledge(entity_id="e1")

        assert len(result) == 1
        mock_db.get_entity_knowledge.assert_called_once_with("e1")
        mock_db.list_knowledge.assert_not_called()

    def test_get_entry(self):
        svc, mock_db, _, _ = _make_service()
        mock_db.get_knowledge_entry.return_value = {
            "id": "1", "content": "Some content",
        }

        result = svc.get_entry("1")

        assert result["content"] == "Some content"

    def test_update_entry(self):
        svc, mock_db, mock_embed, _ = _make_service()
        mock_embed.embed_one.return_value = [0.5]
        mock_db.update_knowledge_entry.return_value = True

        result = svc.update_entry("1", "New content")

        assert result is True
        mock_embed.embed_one.assert_called_once_with("New content")
        mock_db.update_knowledge_entry.assert_called_once_with("1", "New content", [0.5])

    def test_deactivate_entry(self):
        svc, mock_db, _, _ = _make_service()
        mock_db.deactivate_knowledge.return_value = True

        result = svc.deactivate_entry("1")

        assert result is True
        mock_db.deactivate_knowledge.assert_called_once_with("1")
