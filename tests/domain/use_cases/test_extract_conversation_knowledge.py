from datetime import datetime, timedelta
from unittest.mock import MagicMock

from backend.commands.knowledge_extract import ExtractConversationKnowledge


def _mock_retriever():
    r = MagicMock()
    r.get_core.return_value = ""
    r.retrieve.return_value = ""
    return r


def _msgs(*pairs):
    """Build message dicts with ids. pairs = [("user", "text"), ...]"""
    return [{"id": f"id-{i}", "role": r, "content": c} for i, (r, c) in enumerate(pairs)]


# ===================================================================
#  execute — stores extracted facts and marks conversations
# ===================================================================

class TestExtractStoresFacts:

    def test_extract_stores_facts(self):
        """Mock DB returns 5+ messages, mock gemini returns facts, verify remember() called."""
        db = MagicMock()
        db.get_unextracted_conversations.return_value = _msgs(
            ("user", "Привет, нужно обсудить оплату"),
            ("assistant", "Конечно, слушаю"),
            ("user", "Ставка автора Иванова — 5000 рублей за статью"),
            ("assistant", "Запомнил"),
            ("user", "И ещё: редактор Петрова теперь работает по понедельникам"),
        )

        memory = MagicMock()
        memory.remember.side_effect = ["eid-1", "eid-2"]

        gemini = MagicMock()
        gemini.call.return_value = {
            "facts": [
                {"text": "Ставка автора Иванова — 5000 рублей за статью", "domain": "payments", "permanent": True},
                {"text": "Редактор Петрова работает по понедельникам", "domain": "editorial", "permanent": False},
            ]
        }

        extractor = ExtractConversationKnowledge(
            memory=memory, db=db, gemini=gemini, retriever=_mock_retriever(),
        )
        result = extractor.execute(chat_id=100)

        assert result == ["eid-1", "eid-2"]
        assert memory.remember.call_count == 2

        first_call = memory.remember.call_args_list[0][1]
        assert first_call["text"] == "Ставка автора Иванова — 5000 рублей за статью"
        assert first_call["domain"] == "payments"
        assert first_call["source"] == "conversation_extract"
        assert first_call["tier"] == "specific"
        assert first_call["expires_at"] is None  # permanent

        second_call = memory.remember.call_args_list[1][1]
        assert second_call["domain"] == "editorial"
        assert second_call["expires_at"] is not None  # transient

        # Conversations marked as extracted
        db.mark_conversations_extracted.assert_called_once()
        marked_ids = db.mark_conversations_extracted.call_args[0][0]
        assert len(marked_ids) == 5


# ===================================================================
#  execute — skips short conversations
# ===================================================================

class TestExtractSkipsShortConversations:

    def test_extract_skips_short_conversations(self):
        """Less than 3 messages → return empty list without calling LLM."""
        db = MagicMock()
        db.get_unextracted_conversations.return_value = _msgs(
            ("user", "Привет"),
            ("assistant", "Здравствуйте"),
        )

        memory = MagicMock()
        gemini = MagicMock()

        extractor = ExtractConversationKnowledge(
            memory=memory, db=db, gemini=gemini, retriever=_mock_retriever(),
        )
        result = extractor.execute(chat_id=100)

        assert result == []
        gemini.call.assert_not_called()
        memory.remember.assert_not_called()
        db.mark_conversations_extracted.assert_not_called()


# ===================================================================
#  execute — dedup via remember
# ===================================================================

class TestExtractDeduplicatesViaRemember:

    def test_extract_deduplicates_via_remember(self):
        """Dedup is handled by MemoryService, not this class.
        We just verify remember() is called for each fact."""
        db = MagicMock()
        db.get_unextracted_conversations.return_value = _msgs(
            ("user", "msg1"), ("assistant", "msg2"), ("user", "msg3"),
        )

        memory = MagicMock()
        memory.remember.return_value = "same-id"

        gemini = MagicMock()
        gemini.call.return_value = {
            "facts": [
                {"text": "fact A", "domain": "general"},
                {"text": "fact B", "domain": "general"},
            ]
        }

        extractor = ExtractConversationKnowledge(
            memory=memory, db=db, gemini=gemini, retriever=_mock_retriever(),
        )
        result = extractor.execute(chat_id=100)

        assert memory.remember.call_count == 2
        assert result == ["same-id", "same-id"]


# ===================================================================
#  execute — no facts from LLM
# ===================================================================

class TestExtractNoFacts:

    def test_extract_returns_empty_when_no_facts(self):
        """LLM returns empty facts list → no remember calls, but conversations still marked."""
        db = MagicMock()
        db.get_unextracted_conversations.return_value = _msgs(
            ("user", "ок"), ("assistant", "хорошо"), ("user", "спасибо"),
        )

        memory = MagicMock()
        gemini = MagicMock()
        gemini.call.return_value = {"facts": []}

        extractor = ExtractConversationKnowledge(
            memory=memory, db=db, gemini=gemini, retriever=_mock_retriever(),
        )
        result = extractor.execute(chat_id=100)

        assert result == []
        memory.remember.assert_not_called()
        # Conversations are still marked as extracted even with no facts
        db.mark_conversations_extracted.assert_called_once()


# ===================================================================
#  execute — default domain
# ===================================================================

class TestExtractDefaultDomain:

    def test_extract_uses_general_domain_when_missing(self):
        """If fact has no domain key, default to 'general'."""
        db = MagicMock()
        db.get_unextracted_conversations.return_value = _msgs(
            ("user", "msg1"), ("assistant", "msg2"), ("user", "msg3"),
        )

        memory = MagicMock()
        memory.remember.return_value = "id-1"

        gemini = MagicMock()
        gemini.call.return_value = {
            "facts": [{"text": "some fact"}]
        }

        extractor = ExtractConversationKnowledge(
            memory=memory, db=db, gemini=gemini, retriever=_mock_retriever(),
        )
        extractor.execute(chat_id=100)

        assert memory.remember.call_args[1]["domain"] == "general"


# ===================================================================
#  execute — permanent vs transient expires_at
# ===================================================================

class TestExtractExpiresAt:

    def test_permanent_fact_has_no_expiry(self):
        db = MagicMock()
        db.get_unextracted_conversations.return_value = _msgs(
            ("user", "msg1"), ("assistant", "msg2"), ("user", "msg3"),
        )

        memory = MagicMock()
        memory.remember.return_value = "id-1"

        gemini = MagicMock()
        gemini.call.return_value = {
            "facts": [{"text": "permanent fact", "domain": "general", "permanent": True}]
        }

        extractor = ExtractConversationKnowledge(
            memory=memory, db=db, gemini=gemini, retriever=_mock_retriever(),
        )
        extractor.execute(chat_id=100)

        assert memory.remember.call_args[1]["expires_at"] is None

    def test_transient_fact_expires_in_30_days(self):
        db = MagicMock()
        db.get_unextracted_conversations.return_value = _msgs(
            ("user", "msg1"), ("assistant", "msg2"), ("user", "msg3"),
        )

        memory = MagicMock()
        memory.remember.return_value = "id-1"

        gemini = MagicMock()
        gemini.call.return_value = {
            "facts": [{"text": "transient fact", "domain": "general", "permanent": False}]
        }

        extractor = ExtractConversationKnowledge(
            memory=memory, db=db, gemini=gemini, retriever=_mock_retriever(),
        )
        before = datetime.utcnow()
        extractor.execute(chat_id=100)

        expires_at = memory.remember.call_args[1]["expires_at"]
        assert expires_at is not None
        assert expires_at - before >= timedelta(days=29)
        assert expires_at - before <= timedelta(days=31)

    def test_missing_permanent_defaults_to_transient(self):
        db = MagicMock()
        db.get_unextracted_conversations.return_value = _msgs(
            ("user", "msg1"), ("assistant", "msg2"), ("user", "msg3"),
        )

        memory = MagicMock()
        memory.remember.return_value = "id-1"

        gemini = MagicMock()
        gemini.call.return_value = {
            "facts": [{"text": "no permanent key", "domain": "general"}]
        }

        extractor = ExtractConversationKnowledge(
            memory=memory, db=db, gemini=gemini, retriever=_mock_retriever(),
        )
        extractor.execute(chat_id=100)

        assert memory.remember.call_args[1]["expires_at"] is not None


# ===================================================================
#  _extract_facts — passes existing knowledge to prompt
# ===================================================================

class TestExtractExistingKnowledge:

    def test_existing_knowledge_passed_to_template(self):
        db = MagicMock()
        db.get_unextracted_conversations.return_value = _msgs(
            ("user", "msg1"), ("assistant", "msg2"), ("user", "msg3"),
        )

        memory = MagicMock()
        memory.remember.return_value = "id-1"

        gemini = MagicMock()
        gemini.call.return_value = {"facts": []}

        retriever = MagicMock()
        retriever.get_core.return_value = ""
        retriever.retrieve.return_value = "- existing fact 1\n- existing fact 2"

        extractor = ExtractConversationKnowledge(
            memory=memory, db=db, gemini=gemini, retriever=retriever,
        )
        extractor.execute(chat_id=100)

        retriever.retrieve.assert_called_once()
        # The prompt passed to gemini should contain existing knowledge
        prompt = gemini.call.call_args[0][0]
        assert "existing fact 1" in prompt
        assert "existing fact 2" in prompt
