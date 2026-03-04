from unittest.mock import MagicMock, patch

from backend.infrastructure.repositories.postgres import DbGateway
from backend.infrastructure.repositories.postgres.email_repo import _normalize_subject
from common.models import IncomingEmail


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


def _make_email(**overrides) -> IncomingEmail:
    defaults = dict(
        uid="1", from_addr="a@b.com", subject="Test", body="body", date="2026-01-01",
        message_id="<msg1@b.com>", in_reply_to="", references="",
    )
    defaults.update(overrides)
    return IncomingEmail(**defaults)


# ===================================================================
#  _normalize_subject
# ===================================================================

class TestNormalizeSubject:

    def test_strips_re_prefix(self):
        assert _normalize_subject("Re: Hello") == "hello"

    def test_strips_fwd_prefix(self):
        assert _normalize_subject("Fwd: Hello") == "hello"

    def test_strips_fw_prefix(self):
        assert _normalize_subject("Fw: Hello") == "hello"

    def test_strips_nested_prefixes(self):
        assert _normalize_subject("Re: Fwd: Re: Hello") == "hello"

    def test_lowercases(self):
        assert _normalize_subject("IMPORTANT SUBJECT") == "important subject"

    def test_strips_whitespace(self):
        assert _normalize_subject("  Re:  Hello  ") == "hello"

    def test_empty_after_strip(self):
        assert _normalize_subject("Re: ") == ""


# ===================================================================
#  find_thread
# ===================================================================

class TestFindThread:

    def test_matches_by_in_reply_to(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = ("thread-abc",)

        result = gw.find_thread(
            message_id="<new@b.com>",
            in_reply_to="<old@b.com>",
            subject="Re: Hello",
        )

        assert result == "thread-abc"
        sql, params = cur.execute.call_args[0]
        assert "FROM email_messages WHERE message_id = %s" in sql
        assert params == ("<old@b.com>",)

    def test_falls_back_to_subject_match(self):
        gw, cur = _make_gw()
        # First call (in_reply_to lookup) returns None, second (subject) returns a match
        cur.fetchone.side_effect = [None, ("thread-subj",)]

        result = gw.find_thread(
            message_id="<new@b.com>",
            in_reply_to="<old@b.com>",
            subject="Re: Hello",
        )

        assert result == "thread-subj"
        calls = cur.execute.call_args_list
        assert len(calls) == 2
        sql2, params2 = calls[1][0]
        assert "FROM email_threads WHERE normalized_subject = %s" in sql2
        assert params2 == ("hello",)

    @patch("backend.infrastructure.repositories.postgres.email_repo.uuid")
    def test_creates_new_thread(self, mock_uuid):
        mock_uuid.uuid4.return_value = MagicMock(hex="deadbeef1234")
        gw, cur = _make_gw()
        # in_reply_to empty, subject lookup returns None
        cur.fetchone.return_value = None

        result = gw.find_thread(
            message_id="<new@b.com>",
            in_reply_to="",
            subject="Brand new topic",
        )

        assert result == "deadbeef1234"
        sql, params = cur.execute.call_args[0]
        assert "INSERT INTO email_threads" in sql
        assert params == ("deadbeef1234", "Brand new topic", "brand new topic")

    @patch("backend.infrastructure.repositories.postgres.email_repo.uuid")
    def test_creates_new_thread_when_subject_empty(self, mock_uuid):
        mock_uuid.uuid4.return_value = MagicMock(hex="aaa111")
        gw, cur = _make_gw()
        cur.fetchone.return_value = None

        result = gw.find_thread(message_id="<x>", in_reply_to="", subject="")

        assert result == "aaa111"
        sql, params = cur.execute.call_args[0]
        assert "INSERT INTO email_threads" in sql


# ===================================================================
#  save_message
# ===================================================================

class TestSaveMessage:

    def test_inserts_with_on_conflict(self):
        gw, cur = _make_gw()
        email = _make_email(to_addr="support@rep.io")

        gw.save_message(thread_id="t1", email=email, direction="inbound")

        sql, params = cur.execute.call_args[0]
        assert "INSERT INTO email_messages" in sql
        assert "ON CONFLICT (message_id) DO NOTHING" in sql
        assert params == (
            "t1", "<msg1@b.com>", "", "a@b.com", "support@rep.io",
            "Test", "body", "2026-01-01", "inbound",
        )


# ===================================================================
#  get_thread_history
# ===================================================================

class TestGetThreadHistory:

    def test_returns_list_of_dicts(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = [
            ("<msg1>", "a@b.com", "c@d.com", "Subj", "body1", "2026-01-01", "inbound"),
        ]

        result = gw.get_thread_history("t1", limit=5)

        assert len(result) == 1
        assert result[0]["message_id"] == "<msg1>"
        assert result[0]["direction"] == "inbound"
        sql, params = cur.execute.call_args[0]
        assert "FROM email_messages" in sql
        assert "LIMIT %s" in sql
        assert params == ("t1", 5)

    def test_empty(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = []

        result = gw.get_thread_history("t1")

        assert result == []


# ===================================================================
#  create_email_decision
# ===================================================================

class TestCreateEmailDecision:

    def test_inserts_and_returns_id(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = ("dec-1",)

        result = gw.create_email_decision(
            task="draft_reply", channel="EMAIL",
            input_message_ids=["<m1>", "<m2>"],
        )

        assert result == "dec-1"
        sql, params = cur.execute.call_args[0]
        assert "INSERT INTO email_decisions" in sql
        assert "RETURNING id" in sql
        assert params == ("draft_reply", "EMAIL", ["<m1>", "<m2>"], "")

    def test_custom_output(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = ("dec-2",)

        gw.create_email_decision(
            task="t", channel="c", input_message_ids=[], output="some text",
        )

        _, params = cur.execute.call_args[0]
        assert params[3] == "some text"


# ===================================================================
#  update_email_decision
# ===================================================================

class TestUpdateEmailDecision:

    def test_updates_status_and_decided_by(self):
        gw, cur = _make_gw()

        gw.update_email_decision("dec-1", status="APPROVED", decided_by="admin")

        sql, params = cur.execute.call_args[0]
        assert "UPDATE email_decisions" in sql
        assert "SET status = %s" in sql
        assert params == ("APPROVED", "admin", "dec-1")

    def test_decided_by_defaults_to_empty_string(self):
        gw, cur = _make_gw()

        gw.update_email_decision("dec-1", status="REJECTED")

        _, params = cur.execute.call_args[0]
        assert params == ("REJECTED", "", "dec-1")


# ===================================================================
#  update_email_decision_output
# ===================================================================

class TestUpdateEmailDecisionOutput:

    def test_updates_output(self):
        gw, cur = _make_gw()

        gw.update_email_decision_output("dec-1", output="new draft")

        sql, params = cur.execute.call_args[0]
        assert "UPDATE email_decisions SET output = %s" in sql
        assert params == ("new draft", "dec-1")


# ===================================================================
#  get_email_decision
# ===================================================================

class TestGetEmailDecision:

    def test_found(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = (
            42, "2026-01-01", "draft_reply", "EMAIL", ["<m1>"],
            "draft text", "PENDING", "", None,
        )

        result = gw.get_email_decision("42")

        assert result is not None
        assert result["id"] == "42"
        assert result["task"] == "draft_reply"
        assert result["input_message_ids"] == ["<m1>"]
        sql, params = cur.execute.call_args[0]
        assert "FROM email_decisions WHERE id = %s" in sql
        assert params == ("42",)

    def test_not_found(self):
        gw, cur = _make_gw()
        cur.fetchone.return_value = None

        result = gw.get_email_decision("nonexistent")

        assert result is None


# ===================================================================
#  get_thread_message_ids
# ===================================================================

class TestGetThreadMessageIds:

    def test_returns_list_of_ids(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = [("<m1>",), ("<m2>",)]

        result = gw.get_thread_message_ids("t1")

        assert result == ["<m1>", "<m2>"]
        sql, params = cur.execute.call_args[0]
        assert "FROM email_messages" in sql
        assert "WHERE thread_id = %s" in sql
        assert params == ("t1",)

    def test_empty(self):
        gw, cur = _make_gw()
        cur.fetchall.return_value = []

        result = gw.get_thread_message_ids("t1")

        assert result == []
