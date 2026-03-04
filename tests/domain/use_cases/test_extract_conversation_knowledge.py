from unittest.mock import MagicMock

from backend.domain.use_cases.extract_conversation_knowledge import ExtractConversationKnowledge


def _mock_retriever():
    r = MagicMock()
    r.get_core.return_value = ""
    return r


# ===================================================================
#  execute — stores extracted facts
# ===================================================================

class TestExtractStoresFacts:

    def test_extract_stores_facts(self):
        """Mock DB returns 5+ messages, mock gemini returns facts, verify remember() called."""
        db = MagicMock()
        db.get_recent_conversations.return_value = [
            {"role": "user", "content": "Привет, нужно обсудить оплату"},
            {"role": "assistant", "content": "Конечно, слушаю"},
            {"role": "user", "content": "Ставка автора Иванова — 5000 рублей за статью"},
            {"role": "assistant", "content": "Запомнил"},
            {"role": "user", "content": "И ещё: редактор Петрова теперь работает по понедельникам"},
        ]

        memory = MagicMock()
        memory.remember.side_effect = ["id-1", "id-2"]

        gemini = MagicMock()
        gemini.call.return_value = {
            "facts": [
                {"text": "Ставка автора Иванова — 5000 рублей за статью", "domain": "payments"},
                {"text": "Редактор Петрова работает по понедельникам", "domain": "editorial"},
            ]
        }

        extractor = ExtractConversationKnowledge(
            memory=memory, db=db, gemini=gemini, retriever=_mock_retriever(),
        )
        result = extractor.execute(chat_id=100, since_hours=24)

        assert result == ["id-1", "id-2"]
        assert memory.remember.call_count == 2

        first_call = memory.remember.call_args_list[0][1]
        assert first_call["text"] == "Ставка автора Иванова — 5000 рублей за статью"
        assert first_call["domain"] == "payments"
        assert first_call["source"] == "conversation_extract"
        assert first_call["tier"] == "specific"

        second_call = memory.remember.call_args_list[1][1]
        assert second_call["domain"] == "editorial"


# ===================================================================
#  execute — skips short conversations
# ===================================================================

class TestExtractSkipsShortConversations:

    def test_extract_skips_short_conversations(self):
        """Less than 3 messages → return empty list without calling LLM."""
        db = MagicMock()
        db.get_recent_conversations.return_value = [
            {"role": "user", "content": "Привет"},
            {"role": "assistant", "content": "Здравствуйте"},
        ]

        memory = MagicMock()
        gemini = MagicMock()

        extractor = ExtractConversationKnowledge(
            memory=memory, db=db, gemini=gemini, retriever=_mock_retriever(),
        )
        result = extractor.execute(chat_id=100, since_hours=24)

        assert result == []
        gemini.call.assert_not_called()
        memory.remember.assert_not_called()


# ===================================================================
#  execute — dedup via remember
# ===================================================================

class TestExtractDeduplicatesViaRemember:

    def test_extract_deduplicates_via_remember(self):
        """Dedup is handled by MemoryService, not this class.
        We just verify remember() is called for each fact."""
        db = MagicMock()
        db.get_recent_conversations.return_value = [
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "msg2"},
            {"role": "user", "content": "msg3"},
        ]

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
        """LLM returns empty facts list → no remember calls."""
        db = MagicMock()
        db.get_recent_conversations.return_value = [
            {"role": "user", "content": "ок"},
            {"role": "assistant", "content": "хорошо"},
            {"role": "user", "content": "спасибо"},
        ]

        memory = MagicMock()
        gemini = MagicMock()
        gemini.call.return_value = {"facts": []}

        extractor = ExtractConversationKnowledge(
            memory=memory, db=db, gemini=gemini, retriever=_mock_retriever(),
        )
        result = extractor.execute(chat_id=100)

        assert result == []
        memory.remember.assert_not_called()


# ===================================================================
#  execute — default domain
# ===================================================================

class TestExtractDefaultDomain:

    def test_extract_uses_general_domain_when_missing(self):
        """If fact has no domain key, default to 'general'."""
        db = MagicMock()
        db.get_recent_conversations.return_value = [
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "msg2"},
            {"role": "user", "content": "msg3"},
        ]

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
