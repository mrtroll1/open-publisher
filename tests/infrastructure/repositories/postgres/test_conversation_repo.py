import json
from unittest.mock import MagicMock

from backend.infrastructure.repositories.postgres import DbGateway


def _make_gw() -> tuple[DbGateway, MagicMock]:
    """Create a DbGateway with a mocked connection/cursor."""
    gw = DbGateway()
    mock_cursor = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_cursor)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    mock_conn = MagicMock()
    mock_conn.closed = False
    mock_conn.cursor.return_value = mock_ctx
    gw._conn = mock_conn
    return gw, mock_cursor


# ===================================================================
#  save_conversation
# ===================================================================

class TestSaveConversation:

    def test_inserts_and_returns_id(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = ("conv-1",)

        result = gw.save_conversation(
            chat_id=100, user_id=42, role="user", content="hello",
        )

        assert result == "conv-1"
        sql, params = cur.execute.call_args[0]
        assert "INSERT INTO conversations" in sql
        assert "RETURNING id" in sql
        assert params == (100, 42, "user", "hello", None, None, json.dumps({}))

    def test_metadata_serialized(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = ("conv-2",)

        gw.save_conversation(
            chat_id=100, user_id=42, role="assistant", content="hi",
            metadata={"model": "gemini", "tokens": 50},
        )

        _, params = cur.execute.call_args[0]
        assert params[6] == json.dumps({"model": "gemini", "tokens": 50})

    def test_reply_to_and_message_id_passed(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = ("conv-3",)

        gw.save_conversation(
            chat_id=100, user_id=42, role="user", content="reply",
            reply_to_id="conv-1", message_id=999,
        )

        _, params = cur.execute.call_args[0]
        assert params == (100, 42, "user", "reply", "conv-1", 999, json.dumps({}))


# ===================================================================
#  get_conversation_by_message_id
# ===================================================================

class TestGetConversationByMessageId:

    def test_found(self):
        gw, cur = _make_gw()
        cur.description = [("id",), ("chat_id",), ("user_id",), ("role",), ("content",), ("reply_to_id",)]
        cur.fetchone.return_value = (123, 100, 42, "user", "hello", 456)

        result = gw.get_conversation_by_message_id(chat_id=100, message_id=999)

        assert result is not None
        assert result["id"] == "123"
        assert result["reply_to_id"] == "456"
        assert result["role"] == "user"
        sql, params = cur.execute.call_args[0]
        assert "FROM conversations WHERE chat_id = %s AND message_id = %s" in sql
        assert params == (100, 999)

    def test_not_found(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = None

        result = gw.get_conversation_by_message_id(chat_id=100, message_id=999)

        assert result is None

    def test_reply_to_id_none_not_stringified(self):
        gw, cur = _make_gw()
        cur.description = [("id",), ("chat_id",), ("role",), ("content",), ("reply_to_id",)]
        cur.fetchone.return_value = (1, 100, "user", "hi", None)

        result = gw.get_conversation_by_message_id(chat_id=100, message_id=1)

        assert result["id"] == "1"
        assert result["reply_to_id"] is None


# ===================================================================
#  get_recent_conversations
# ===================================================================

class TestGetRecentConversations:

    def test_returns_list_of_dicts(self):
        gw, cur = _make_gw()
        cur.description = [("role",), ("content",), ("created_at",)]
        cur.fetchall.return_value = [
            ("user", "hello", "2026-01-01 10:00"),
            ("assistant", "hi", "2026-01-01 10:01"),
        ]

        result = gw.get_recent_conversations(chat_id=100, hours=12)

        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[1]["content"] == "hi"
        sql, params = cur.execute.call_args[0]
        assert "FROM conversations" in sql
        assert "INTERVAL '1 hour'" in sql
        assert params == (100, 12)

    def test_empty(self):
        gw, cur = _make_gw()
        cur.description = [("role",), ("content",), ("created_at",)]
        cur.fetchall.return_value = []

        result = gw.get_recent_conversations(chat_id=100)

        assert result == []


# ===================================================================
#  get_reply_chain
# ===================================================================

class TestGetReplyChain:

    def _mock_description(self):
        return [("id",), ("chat_id",), ("role",), ("content",), ("reply_to_id",)]

    def test_not_found_returns_empty(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = None

        result = gw.get_reply_chain("nonexistent")

        assert result == []

    def test_single_message_no_reply(self):
        gw, cur = _make_gw()
        cur.description = self._mock_description()
        cur.fetchone.return_value = (10, 100, "user", "root message", None)

        result = gw.get_reply_chain("10")

        assert len(result) == 1
        assert result[0]["id"] == "10"
        assert result[0]["content"] == "root message"

    def test_chain_of_three_reversed(self):
        gw, cur = _make_gw()
        cur.description = self._mock_description()
        cur.fetchone.side_effect = [
            (3, 100, "assistant", "reply2", 2),
            (2, 100, "user", "reply1", 1),
            (1, 100, "user", "root", None),
        ]

        result = gw.get_reply_chain("3")

        assert len(result) == 3
        # Reversed: root first
        assert result[0]["id"] == "1"
        assert result[1]["id"] == "2"
        assert result[2]["id"] == "3"

    def test_chain_stops_on_missing_row(self):
        gw, cur = _make_gw()
        cur.description = self._mock_description()
        cur.fetchone.side_effect = [
            (5, 100, "user", "msg", 4),
            None,  # parent not found
        ]

        result = gw.get_reply_chain("5")

        assert len(result) == 1
        assert result[0]["id"] == "5"

    def test_chain_respects_depth_limit(self):
        gw, cur = _make_gw()
        cur.description = self._mock_description()
        # Always returns a row that points to a parent (infinite chain)
        cur.fetchone.side_effect = [
            (i, 100, "user", f"msg-{i}", i - 1) for i in range(100, 97, -1)
        ]

        result = gw.get_reply_chain("100", depth=3)

        assert len(result) == 3
