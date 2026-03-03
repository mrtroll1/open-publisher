import json
from unittest.mock import MagicMock

import pytest

from backend.infrastructure.repositories.postgres import DbGateway, _normalize_subject


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Hello World", "hello world"),
        ("Re: Something", "something"),
        ("Fwd: Something", "something"),
        ("Fw: Something", "something"),
        ("Re: Fwd: Re: Topic", "topic"),
        ("RE: LOUD SUBJECT", "loud subject"),
        ("re: quiet subject", "quiet subject"),
        ("FWD: Forwarded", "forwarded"),
        ("fwd: forwarded", "forwarded"),
        ("Fw: FW: fw: nested", "nested"),
        ("  spaces around  ", "spaces around"),
        ("Re:  extra spaces", "extra spaces"),
        ("", ""),
        ("No prefix here", "no prefix here"),
        ("Regarding something", "regarding something"),
        ("Re: Re: Re: deep", "deep"),
    ],
    ids=[
        "basic_lowercase",
        "re_prefix",
        "fwd_prefix",
        "fw_prefix",
        "nested_prefixes",
        "uppercase_RE",
        "lowercase_re",
        "uppercase_FWD",
        "lowercase_fwd",
        "mixed_fw_variants",
        "leading_trailing_whitespace",
        "re_extra_spaces",
        "empty_string",
        "no_prefix",
        "regarding_not_stripped",
        "triple_re",
    ],
)
def test_normalize_subject(raw: str, expected: str) -> None:
    assert _normalize_subject(raw) == expected


# ===================================================================
#  email_decisions CRUD
# ===================================================================

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


class TestEmailDecisionsCRUD:

    def test_create_email_decision(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = ("abc-123",)

        result = gw.create_email_decision(
            task="SUPPORT_ANSWER", channel="EMAIL",
            input_message_ids=["<msg1>", "<msg2>"], output="draft text",
        )

        assert result == "abc-123"
        sql, params = cur.execute.call_args[0]
        assert "INSERT INTO email_decisions" in sql
        assert "RETURNING id" in sql
        assert params == ("SUPPORT_ANSWER", "EMAIL", ["<msg1>", "<msg2>"], "draft text")

    def test_create_email_decision_default_output(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = ("def-456",)

        result = gw.create_email_decision(
            task="ARTICLE_APPROVAL", channel="EMAIL",
            input_message_ids=["<msg1>"],
        )

        assert result == "def-456"
        _, params = cur.execute.call_args[0]
        assert params[3] == ""  # default output

    def test_update_email_decision(self):
        gw, cur = _make_gw()

        gw.update_email_decision("abc-123", "APPROVED", decided_by="admin")

        sql, params = cur.execute.call_args[0]
        assert "UPDATE email_decisions" in sql
        assert "SET status" in sql
        assert params == ("APPROVED", "admin", "abc-123")

    def test_update_email_decision_no_decided_by(self):
        gw, cur = _make_gw()

        gw.update_email_decision("abc-123", "REJECTED")

        _, params = cur.execute.call_args[0]
        assert params == ("REJECTED", "", "abc-123")

    def test_update_email_decision_output(self):
        gw, cur = _make_gw()

        gw.update_email_decision_output("abc-123", "new draft text")

        sql, params = cur.execute.call_args[0]
        assert "UPDATE email_decisions SET output" in sql
        assert params == ("new draft text", "abc-123")

    def test_get_email_decision_found(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = (
            "abc-123", "2026-01-01", "SUPPORT_ANSWER", "EMAIL",
            ["<msg1>"], "reply text", "APPROVED", "admin", "2026-01-02",
        )

        result = gw.get_email_decision("abc-123")

        assert result is not None
        assert result["id"] == "abc-123"
        assert result["task"] == "SUPPORT_ANSWER"
        assert result["status"] == "APPROVED"
        assert result["output"] == "reply text"
        assert result["decided_by"] == "admin"

    def test_get_email_decision_not_found(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = None

        result = gw.get_email_decision("nonexistent")

        assert result is None


# ===================================================================
#  get_thread_message_ids
# ===================================================================

class TestGetThreadMessageIds:

    def test_returns_message_ids(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = [("<msg1>",), ("<msg2>",), ("<msg3>",)]

        result = gw.get_thread_message_ids("thread-abc")

        assert result == ["<msg1>", "<msg2>", "<msg3>"]
        sql, params = cur.execute.call_args[0]
        assert "SELECT message_id FROM email_messages" in sql
        assert "WHERE thread_id" in sql
        assert params == ("thread-abc",)

    def test_empty_thread(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = []

        result = gw.get_thread_message_ids("thread-empty")

        assert result == []


# ===================================================================
#  log_classification
# ===================================================================

class TestLogClassification:

    def test_inserts_correct_data(self):
        gw, cur = _make_gw()

        gw.log_classification(
            task="INBOX_CLASSIFY", model="gemini-2.5-flash",
            input_text="some prompt", output_json='{"category": "tech_support"}',
            latency_ms=150,
        )

        sql, params = cur.execute.call_args[0]
        assert "INSERT INTO llm_classifications" in sql
        assert params == (
            "INBOX_CLASSIFY", "gemini-2.5-flash",
            "some prompt", '{"category": "tech_support"}', 150,
        )

    def test_zero_latency(self):
        gw, cur = _make_gw()

        gw.log_classification(
            task="COMMAND_CLASSIFY", model="gemini-2.5-flash",
            input_text="prompt", output_json='{}', latency_ms=0,
        )

        _, params = cur.execute.call_args[0]
        assert params[4] == 0


# ===================================================================
#  log_payment_validation
# ===================================================================

class TestLogPaymentValidation:

    def test_inserts_and_returns_id(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = ("val-abc-123",)

        result = gw.log_payment_validation(
            contractor_id="", contractor_type="IP",
            input_text="ИП Иванов, ИНН 1234567890",
            parsed_json='{"name": "Иванов"}',
        )

        assert result == "val-abc-123"
        sql, params = cur.execute.call_args[0]
        assert "INSERT INTO payment_validations" in sql
        assert "RETURNING id" in sql
        assert params == ("", "IP", "ИП Иванов, ИНН 1234567890", '{"name": "Иванов"}', [], False)

    def test_with_warnings_and_is_final(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = ("val-def-456",)

        result = gw.log_payment_validation(
            contractor_id="C-001", contractor_type="SELF_EMPLOYED",
            input_text="test data",
            parsed_json='{"field": "value"}',
            warnings=["ИНН должен содержать 12 цифр"],
            is_final=True,
        )

        assert result == "val-def-456"
        _, params = cur.execute.call_args[0]
        assert params == (
            "C-001", "SELF_EMPLOYED", "test data", '{"field": "value"}',
            ["ИНН должен содержать 12 цифр"], True,
        )

    def test_default_warnings_empty_list(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = ("val-xyz",)

        gw.log_payment_validation(
            contractor_id="", contractor_type="IP",
            input_text="text", parsed_json="{}",
        )

        _, params = cur.execute.call_args[0]
        assert params[4] == []  # warnings default to empty list
        assert params[5] is False  # is_final default


# ===================================================================
#  finalize_payment_validation
# ===================================================================

class TestFinalizePaymentValidation:

    def test_updates_is_final(self):
        gw, cur = _make_gw()

        gw.finalize_payment_validation("val-abc-123")

        sql, params = cur.execute.call_args[0]
        assert "UPDATE payment_validations" in sql
        assert "SET is_final = TRUE" in sql
        assert params == ("val-abc-123",)


# ===================================================================
#  code_tasks CRUD
# ===================================================================

class TestCodeTasksCRUD:

    def test_create_code_task(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = ("task-uuid-123",)

        result = gw.create_code_task(
            requested_by="user42",
            input_text="fix the bug",
            output_text="here is the fix ...",
        )

        assert result == "task-uuid-123"
        sql, params = cur.execute.call_args[0]
        assert "INSERT INTO code_tasks" in sql
        assert "RETURNING id" in sql
        assert params == ("user42", "fix the bug", "here is the fix ...", False)

    def test_create_code_task_verbose(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = ("task-verbose-456",)

        result = gw.create_code_task(
            requested_by="user42",
            input_text="explain this code",
            output_text="detailed explanation ...",
            verbose=True,
        )

        assert result == "task-verbose-456"
        _, params = cur.execute.call_args[0]
        assert params[3] is True

    def test_rate_code_task(self):
        gw, cur = _make_gw()

        gw.rate_code_task("task-uuid-123", 5)

        sql, params = cur.execute.call_args[0]
        assert "UPDATE code_tasks" in sql
        assert "SET rating" in sql
        assert "rated_at = NOW()" in sql
        assert params == (5, "task-uuid-123")


# ===================================================================
#  conversations CRUD
# ===================================================================

class TestConversationsCRUD:

    def test_save_conversation_returns_uuid(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = ("conv-uuid-111",)

        result = gw.save_conversation(
            chat_id=100, user_id=42, role="user", content="hello",
        )

        assert result == "conv-uuid-111"
        sql, params = cur.execute.call_args[0]
        assert "INSERT INTO conversations" in sql
        assert "RETURNING id" in sql
        assert params == (100, 42, "user", "hello", None, None, "{}")

    def test_save_conversation_with_metadata(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = ("conv-uuid-222",)

        meta = {"command": "code", "channel": "dm"}
        result = gw.save_conversation(
            chat_id=100, user_id=42, role="assistant", content="reply",
            metadata=meta,
        )

        assert result == "conv-uuid-222"
        _, params = cur.execute.call_args[0]
        assert params[6] == json.dumps(meta)

    def test_save_conversation_defaults(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = ("conv-uuid-333",)

        gw.save_conversation(chat_id=1, user_id=2, role="user", content="hi")

        _, params = cur.execute.call_args[0]
        assert params[4] is None  # reply_to_id
        assert params[5] is None  # message_id
        assert params[6] == "{}"  # metadata defaults to empty dict JSON

    def test_get_conversation_by_message_id_found(self):
        gw, cur = _make_gw()
        cur.description = [
            ("id",), ("chat_id",), ("user_id",), ("role",), ("content",),
            ("reply_to_id",), ("message_id",), ("metadata",), ("created_at",),
        ]
        cur.fetchone.return_value = (
            "conv-uuid-444", 100, 42, "user", "hello",
            None, 999, {}, "2026-03-01",
        )

        result = gw.get_conversation_by_message_id(chat_id=100, message_id=999)

        assert result is not None
        assert result["id"] == "conv-uuid-444"
        assert result["chat_id"] == 100
        assert result["role"] == "user"
        assert result["content"] == "hello"
        sql, params = cur.execute.call_args[0]
        assert "WHERE chat_id = %s AND message_id = %s" in sql
        assert params == (100, 999)

    def test_get_conversation_by_message_id_not_found(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = None

        result = gw.get_conversation_by_message_id(chat_id=100, message_id=999)

        assert result is None

    def test_get_reply_chain(self):
        gw, cur = _make_gw()
        cur.description = [
            ("id",), ("chat_id",), ("user_id",), ("role",), ("content",),
            ("reply_to_id",), ("message_id",), ("metadata",), ("created_at",),
        ]
        # Walk starts from id-3 → id-2 → id-1 (no reply_to)
        rows = [
            ("id-3", 100, 42, "assistant", "c", "id-2", 3, {}, "t3"),
            ("id-2", 100, 42, "user", "b", "id-1", 2, {}, "t2"),
            ("id-1", 100, 42, "user", "a", None, 1, {}, "t1"),
        ]
        cur.fetchone.side_effect = list(rows)

        result = gw.get_reply_chain("id-3", depth=10)

        # Chronological order (reversed from walk)
        assert len(result) == 3
        assert result[0]["id"] == "id-1"
        assert result[1]["id"] == "id-2"
        assert result[2]["id"] == "id-3"

    def test_get_reply_chain_empty(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = None

        result = gw.get_reply_chain("nonexistent")

        assert result == []

    def test_get_reply_chain_depth_limit(self):
        gw, cur = _make_gw()
        cur.description = [
            ("id",), ("chat_id",), ("user_id",), ("role",), ("content",),
            ("reply_to_id",), ("message_id",), ("metadata",), ("created_at",),
        ]
        # Chain of 5 records, but depth=2 should stop after 2
        cur.fetchone.side_effect = [
            ("id-5", 100, 42, "assistant", "e", "id-4", 5, {}, "t5"),
            ("id-4", 100, 42, "user", "d", "id-3", 4, {}, "t4"),
        ]

        result = gw.get_reply_chain("id-5", depth=2)

        assert len(result) == 2
        assert result[0]["id"] == "id-4"
        assert result[1]["id"] == "id-5"
