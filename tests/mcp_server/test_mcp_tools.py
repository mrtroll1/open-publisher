from unittest.mock import MagicMock
from datetime import datetime, timedelta, timezone

import mcp_server.server as srv


def _setup(mock_memory):
    srv._memory = mock_memory


def _make_mock():
    return MagicMock()


# ===================================================================
#  remember
# ===================================================================

class TestRemember:

    def test_stores_and_returns_id(self):
        mem = _make_mock()
        mem.remember.return_value = "entry-123"
        _setup(mem)

        result = srv.remember("some fact", domain="general")

        assert result == {"id": "entry-123"}
        mem.remember.assert_called_once_with(
            "some fact", "general", source="mcp", tier="specific",
            entity_id=None, source_url=None, expires_at=None,
        )

    def test_expires_in_days_converted(self):
        mem = _make_mock()
        mem.remember.return_value = "entry-456"
        _setup(mem)

        before = datetime.now(timezone.utc)
        result = srv.remember("expiring fact", domain="billing", expires_in_days=30)
        after = datetime.now(timezone.utc)

        assert result == {"id": "entry-456"}
        call_kwargs = mem.remember.call_args
        expires_at = call_kwargs[1]["expires_at"]
        assert before + timedelta(days=30) <= expires_at <= after + timedelta(days=30)

    def test_zero_expires_means_no_expiry(self):
        mem = _make_mock()
        mem.remember.return_value = "id"
        _setup(mem)

        srv.remember("fact", domain="d", expires_in_days=0)

        assert mem.remember.call_args[1]["expires_at"] is None

    def test_entity_name_resolved(self):
        mem = _make_mock()
        mem.find_entity.return_value = {"id": "ent-1", "name": "Alice"}
        mem.remember.return_value = "id"
        _setup(mem)

        srv.remember("fact about Alice", domain="general", entity_name="Alice")

        mem.find_entity.assert_called_once_with(query="Alice")
        assert mem.remember.call_args[1]["entity_id"] == "ent-1"

    def test_entity_name_not_found(self):
        mem = _make_mock()
        mem.find_entity.return_value = None
        mem.remember.return_value = "id"
        _setup(mem)

        srv.remember("fact", domain="general", entity_name="Nobody")

        assert mem.remember.call_args[1]["entity_id"] is None

    def test_source_url_empty_string_becomes_none(self):
        mem = _make_mock()
        mem.remember.return_value = "id"
        _setup(mem)

        srv.remember("fact", domain="d", source_url="")

        assert mem.remember.call_args[1]["source_url"] is None

    def test_source_url_passed_through(self):
        mem = _make_mock()
        mem.remember.return_value = "id"
        _setup(mem)

        srv.remember("fact", domain="d", source_url="https://x.com")

        assert mem.remember.call_args[1]["source_url"] == "https://x.com"


# ===================================================================
#  recall
# ===================================================================

class TestRecall:

    def test_returns_results(self):
        mem = _make_mock()
        mem.recall.return_value = [
            {"id": "1", "title": "T", "content": "C", "similarity": 0.9},
        ]
        _setup(mem)

        result = srv.recall("query")

        assert result == {"results": [
            {"id": "1", "title": "T", "content": "C", "similarity": 0.9},
        ]}
        mem.recall.assert_called_once_with("query", domain=None, limit=5)

    def test_with_domain_filter(self):
        mem = _make_mock()
        mem.recall.return_value = []
        _setup(mem)

        srv.recall("q", domain="billing", limit=3)

        mem.recall.assert_called_once_with("q", domain="billing", limit=3)

    def test_empty_domain_becomes_none(self):
        mem = _make_mock()
        mem.recall.return_value = []
        _setup(mem)

        srv.recall("q", domain="")

        mem.recall.assert_called_once_with("q", domain=None, limit=5)


# ===================================================================
#  teach
# ===================================================================

class TestTeach:

    def test_auto_classifies_and_returns_all(self):
        mem = _make_mock()
        mem.classify_teaching.return_value = ("editorial", "meta")
        mem.teach.return_value = "teach-id"
        _setup(mem)

        result = srv.teach("Always greet in Russian")

        assert result == {"id": "teach-id", "domain": "editorial", "tier": "meta"}
        mem.classify_teaching.assert_called_once_with("Always greet in Russian")
        mem.teach.assert_called_once_with(
            "Always greet in Russian", domain="editorial", tier="meta",
        )


# ===================================================================
#  get_context
# ===================================================================

class TestGetContext:

    def test_returns_context_dict(self):
        mem = _make_mock()
        mem.get_context.return_value = {
            "environment": "ctx", "knowledge": "k",
            "user_context": "", "domains": ["d"],
        }
        _setup(mem)

        result = srv.get_context(environment="prod", query="billing")

        assert result["environment"] == "ctx"
        assert result["domains"] == ["d"]
        mem.get_context.assert_called_once_with(
            environment="prod", query="billing",
        )

    def test_empty_environment_becomes_none(self):
        mem = _make_mock()
        mem.get_context.return_value = {
            "environment": "", "knowledge": "", "user_context": "", "domains": [],
        }
        _setup(mem)

        srv.get_context()

        mem.get_context.assert_called_once_with(environment=None, query="")


# ===================================================================
#  list_domains
# ===================================================================

class TestListDomains:

    def test_returns_domains(self):
        mem = _make_mock()
        mem.list_domains.return_value = [
            {"name": "general", "description": "General"},
        ]
        _setup(mem)

        result = srv.list_domains()

        assert result == {"domains": [
            {"name": "general", "description": "General"},
        ]}


# ===================================================================
#  list_environments
# ===================================================================

class TestListEnvironments:

    def test_returns_environments(self):
        mem = _make_mock()
        mem.list_environments.return_value = [
            {"name": "prod"}, {"name": "staging"},
        ]
        _setup(mem)

        result = srv.list_environments()

        assert result == {"environments": [
            {"name": "prod"}, {"name": "staging"},
        ]}


# ===================================================================
#  find_entity
# ===================================================================

class TestFindEntity:

    def test_by_query(self):
        mem = _make_mock()
        mem.find_entity.return_value = {"id": "e1", "name": "Alice"}
        _setup(mem)

        result = srv.find_entity(query="Alice")

        assert result == {"entity": {"id": "e1", "name": "Alice"}}
        mem.find_entity.assert_called_once_with(query="Alice")

    def test_not_found(self):
        mem = _make_mock()
        mem.find_entity.return_value = None
        _setup(mem)

        result = srv.find_entity(query="Nobody")

        assert result == {"entity": None}


# ===================================================================
#  add_entity
# ===================================================================

class TestAddEntity:

    def test_creates_entity(self):
        mem = _make_mock()
        mem.add_entity.return_value = "entity-uuid"
        _setup(mem)

        result = srv.add_entity("person", "John Doe", summary="Dev")

        assert result == {"id": "entity-uuid"}
        mem.add_entity.assert_called_once_with(
            "person", "John Doe", summary="Dev",
        )


# ===================================================================
#  entity_note
# ===================================================================

class TestEntityNote:

    def test_attaches_note(self):
        mem = _make_mock()
        mem.find_entity.return_value = {"id": "e1", "name": "Alice"}
        mem.remember.return_value = "note-id"
        _setup(mem)

        result = srv.entity_note("Alice", "Prefers email communication")

        assert result == {"id": "note-id"}
        mem.find_entity.assert_called_once_with(query="Alice")
        mem.remember.assert_called_once_with(
            "Prefers email communication", domain="general", entity_id="e1",
        )

    def test_custom_domain(self):
        mem = _make_mock()
        mem.find_entity.return_value = {"id": "e1", "name": "Alice"}
        mem.remember.return_value = "id"
        _setup(mem)

        srv.entity_note("Alice", "Payment info", domain="billing")

        mem.remember.assert_called_once_with(
            "Payment info", domain="billing", entity_id="e1",
        )

    def test_entity_not_found(self):
        mem = _make_mock()
        mem.find_entity.return_value = None
        _setup(mem)

        result = srv.entity_note("Nobody", "Some note")

        assert result == {"error": "Entity 'Nobody' not found"}
        mem.remember.assert_not_called()


# ===================================================================
#  list_knowledge
# ===================================================================

class TestListKnowledge:

    def test_by_domain(self):
        mem = _make_mock()
        mem.list_knowledge.return_value = [
            {"id": "1", "title": "T", "content": "C"},
        ]
        _setup(mem)

        result = srv.list_knowledge(domain="general")

        assert result == {"entries": [
            {"id": "1", "title": "T", "content": "C"},
        ]}
        mem.list_knowledge.assert_called_once_with(
            domain="general", tier=None,
        )

    def test_no_filters(self):
        mem = _make_mock()
        mem.list_knowledge.return_value = []
        _setup(mem)

        result = srv.list_knowledge()

        assert result == {"entries": []}
        mem.list_knowledge.assert_called_once_with(
            domain=None, tier=None,
        )

    def test_both_domain_and_tier_filters(self):
        mem = _make_mock()
        mem.list_knowledge.return_value = [
            {"id": "x", "title": "X", "content": "body"},
        ]
        _setup(mem)

        result = srv.list_knowledge(domain="editorial", tier="meta")

        assert result == {"entries": [
            {"id": "x", "title": "X", "content": "body"},
        ]}
        mem.list_knowledge.assert_called_once_with(
            domain="editorial", tier="meta",
        )

    def test_empty_tier_becomes_none(self):
        mem = _make_mock()
        mem.list_knowledge.return_value = []
        _setup(mem)

        srv.list_knowledge(tier="")

        mem.list_knowledge.assert_called_once_with(
            domain=None, tier=None,
        )

    def test_empty_domain_becomes_none(self):
        mem = _make_mock()
        mem.list_knowledge.return_value = []
        _setup(mem)

        srv.list_knowledge(domain="")

        mem.list_knowledge.assert_called_once_with(
            domain=None, tier=None,
        )


# ===================================================================
#  remember — additional edge cases
# ===================================================================

class TestRememberEdgeCases:

    def test_negative_expires_in_days_still_computes(self):
        """Negative days is truthy so expires_at gets set (edge case)."""
        mem = _make_mock()
        mem.remember.return_value = "id"
        _setup(mem)

        srv.remember("fact", domain="d", expires_in_days=-1)

        expires_at = mem.remember.call_args[1]["expires_at"]
        # Should be a datetime in the past
        assert expires_at is not None
        assert expires_at < datetime.now(timezone.utc)

    def test_custom_tier_passed_through(self):
        mem = _make_mock()
        mem.remember.return_value = "id"
        _setup(mem)

        srv.remember("fact", domain="d", tier="core")

        assert mem.remember.call_args[1]["tier"] == "core"

    def test_custom_source_passed_through(self):
        mem = _make_mock()
        mem.remember.return_value = "id"
        _setup(mem)

        srv.remember("fact", domain="d", source="custom_pipeline")

        assert mem.remember.call_args[1]["source"] == "custom_pipeline"

    def test_entity_name_empty_string_skips_lookup(self):
        """Empty entity_name should not trigger find_entity."""
        mem = _make_mock()
        mem.remember.return_value = "id"
        _setup(mem)

        srv.remember("fact", domain="d", entity_name="")

        mem.find_entity.assert_not_called()
        assert mem.remember.call_args[1]["entity_id"] is None


# ===================================================================
#  recall — additional edge cases
# ===================================================================

class TestRecallEdgeCases:

    def test_custom_limit(self):
        mem = _make_mock()
        mem.recall.return_value = []
        _setup(mem)

        srv.recall("q", limit=20)

        mem.recall.assert_called_once_with("q", domain=None, limit=20)

    def test_empty_results(self):
        mem = _make_mock()
        mem.recall.return_value = []
        _setup(mem)

        result = srv.recall("nonexistent query")

        assert result == {"results": []}

    def test_multiple_results_returned(self):
        mem = _make_mock()
        mem.recall.return_value = [
            {"id": "1", "title": "A", "content": "a", "similarity": 0.9},
            {"id": "2", "title": "B", "content": "b", "similarity": 0.7},
            {"id": "3", "title": "C", "content": "c", "similarity": 0.5},
        ]
        _setup(mem)

        result = srv.recall("query")

        assert len(result["results"]) == 3


# ===================================================================
#  add_entity — additional edge cases
# ===================================================================

class TestAddEntityEdgeCases:

    def test_default_summary_empty(self):
        mem = _make_mock()
        mem.add_entity.return_value = "id"
        _setup(mem)

        srv.add_entity("organization", "Acme Corp")

        mem.add_entity.assert_called_once_with(
            "organization", "Acme Corp", summary="",
        )


# ===================================================================
#  entity_note — resolve_entity uses _get_memory
# ===================================================================

class TestEntityNoteEdgeCases:

    def test_entity_note_uses_resolve_entity_internally(self):
        """entity_note calls _resolve_entity which uses find_entity(query=...)."""
        mem = _make_mock()
        mem.find_entity.return_value = {"id": "e99", "name": "Bob"}
        mem.remember.return_value = "note-99"
        _setup(mem)

        result = srv.entity_note("Bob", "Important note", domain="tech")

        assert result == {"id": "note-99"}
        mem.find_entity.assert_called_once_with(query="Bob")
        mem.remember.assert_called_once_with(
            "Important note", domain="tech", entity_id="e99",
        )


# ===================================================================
#  get_context — additional edge cases
# ===================================================================

class TestGetContextEdgeCases:

    def test_query_passed_through(self):
        mem = _make_mock()
        mem.get_context.return_value = {
            "environment": "", "knowledge": "k",
            "user_context": "", "domains": [],
        }
        _setup(mem)

        srv.get_context(query="billing invoices")

        mem.get_context.assert_called_once_with(
            environment=None, query="billing invoices",
        )

    def test_both_environment_and_query(self):
        mem = _make_mock()
        mem.get_context.return_value = {
            "environment": "ctx", "knowledge": "k",
            "user_context": "", "domains": ["d"],
        }
        _setup(mem)

        srv.get_context(environment="editorial", query="articles")

        mem.get_context.assert_called_once_with(
            environment="editorial", query="articles",
        )
