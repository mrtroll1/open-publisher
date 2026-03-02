"""Tests for InboxService decision tracking in approve/skip workflows."""

from unittest.mock import MagicMock, patch

import pytest

from common.models import EditorialItem, IncomingEmail, SupportDraft


def _make_email(**overrides) -> IncomingEmail:
    defaults = dict(
        uid="uid-1", from_addr="user@test.com", to_addr="support@test.com",
        subject="Help", body="I need help", date="2026-01-15",
        message_id="<msg-1>",
    )
    defaults.update(overrides)
    return IncomingEmail(**defaults)


def _make_draft(email: IncomingEmail | None = None, decision_id: str = "dec-1") -> SupportDraft:
    return SupportDraft(
        email=email or _make_email(),
        can_answer=True,
        draft_reply="Here is the answer.",
        decision_id=decision_id,
    )


def _make_editorial_item(email: IncomingEmail | None = None, decision_id: str = "dec-2") -> EditorialItem:
    return EditorialItem(
        email=email or _make_email(),
        reply_to_sender="Thanks for writing.",
        decision_id=decision_id,
    )


@patch("backend.domain.inbox_service.DbGateway")
@patch("backend.domain.inbox_service.EmailGateway")
@patch("backend.domain.inbox_service.GeminiGateway")
@patch("backend.domain.inbox_service.TechSupportHandler")
def _make_service(MockTSH, MockGemini, MockEmail, MockDb):
    """Create InboxService with all dependencies mocked."""
    from backend.domain.inbox_service import InboxService
    svc = InboxService()
    return svc, svc._db, svc._email_gw, svc._tech_support


# ===================================================================
#  approve_support — decision tracking
# ===================================================================

class TestApproveSupportDecision:

    def test_approve_updates_decision_approved(self):
        svc, mock_db, mock_email, mock_tsh = _make_service()
        draft = _make_draft(decision_id="dec-support-1")
        svc._pending_support["uid-1"] = draft

        result = svc.approve_support("uid-1")

        assert result is draft
        mock_db.update_email_decision_output.assert_called_once_with("dec-support-1", draft.draft_reply)
        mock_db.update_email_decision.assert_called_once_with("dec-support-1", "APPROVED", decided_by="admin")

    def test_approve_without_decision_id_skips_db(self):
        svc, mock_db, mock_email, mock_tsh = _make_service()
        draft = _make_draft(decision_id="")
        svc._pending_support["uid-1"] = draft

        svc.approve_support("uid-1")

        mock_db.update_email_decision_output.assert_not_called()
        mock_db.update_email_decision.assert_not_called()

    def test_approve_sends_email_and_marks_read(self):
        svc, mock_db, mock_email, mock_tsh = _make_service()
        email = _make_email()
        draft = _make_draft(email=email)
        svc._pending_support["uid-1"] = draft

        svc.approve_support("uid-1")

        mock_email.send_reply.assert_called_once()
        mock_email.mark_read.assert_called_once_with("uid-1")

    def test_approve_nonexistent_uid_returns_none(self):
        svc, mock_db, _, _ = _make_service()

        result = svc.approve_support("nonexistent")

        assert result is None
        mock_db.update_email_decision.assert_not_called()


# ===================================================================
#  skip_support — decision tracking + discard
# ===================================================================

class TestSkipSupportDecision:

    def test_skip_updates_decision_rejected(self):
        svc, mock_db, _, mock_tsh = _make_service()
        draft = _make_draft(decision_id="dec-support-2")
        svc._pending_support["uid-1"] = draft

        svc.skip_support("uid-1")

        mock_db.update_email_decision.assert_called_once_with("dec-support-2", "REJECTED", decided_by="admin")

    def test_skip_calls_discard_with_draft(self):
        svc, mock_db, _, mock_tsh = _make_service()
        draft = _make_draft(decision_id="dec-support-2")
        svc._pending_support["uid-1"] = draft

        svc.skip_support("uid-1")

        mock_tsh.discard.assert_called_once_with("uid-1", draft=draft)

    def test_skip_without_decision_id_skips_db(self):
        svc, mock_db, _, mock_tsh = _make_service()
        draft = _make_draft(decision_id="")
        svc._pending_support["uid-1"] = draft

        svc.skip_support("uid-1")

        mock_db.update_email_decision.assert_not_called()
        mock_tsh.discard.assert_called_once()

    def test_skip_nonexistent_uid_still_discards(self):
        svc, mock_db, _, mock_tsh = _make_service()

        svc.skip_support("nonexistent")

        mock_db.update_email_decision.assert_not_called()
        mock_tsh.discard.assert_called_once_with("nonexistent", draft=None)


# ===================================================================
#  approve_editorial — decision tracking
# ===================================================================

class TestApproveEditorialDecision:

    @patch("backend.domain.inbox_service.CHIEF_EDITOR_EMAIL", "editor@test.com")
    def test_approve_updates_decision_approved(self):
        svc, mock_db, mock_email, _ = _make_service()
        item = _make_editorial_item(decision_id="dec-edit-1")
        svc._pending_editorial["uid-1"] = item

        result = svc.approve_editorial("uid-1")

        assert result is item
        mock_db.update_email_decision.assert_called_once_with("dec-edit-1", "APPROVED", decided_by="admin")

    @patch("backend.domain.inbox_service.CHIEF_EDITOR_EMAIL", "editor@test.com")
    def test_approve_without_decision_id_skips_db(self):
        svc, mock_db, mock_email, _ = _make_service()
        item = _make_editorial_item(decision_id="")
        svc._pending_editorial["uid-1"] = item

        svc.approve_editorial("uid-1")

        mock_db.update_email_decision.assert_not_called()

    def test_approve_nonexistent_uid_returns_none(self):
        svc, mock_db, _, _ = _make_service()

        result = svc.approve_editorial("nonexistent")

        assert result is None
        mock_db.update_email_decision.assert_not_called()


# ===================================================================
#  skip_editorial — decision tracking
# ===================================================================

class TestSkipEditorialDecision:

    def test_skip_updates_decision_rejected(self):
        svc, mock_db, _, _ = _make_service()
        item = _make_editorial_item(decision_id="dec-edit-2")
        svc._pending_editorial["uid-1"] = item

        svc.skip_editorial("uid-1")

        mock_db.update_email_decision.assert_called_once_with("dec-edit-2", "REJECTED", decided_by="admin")

    def test_skip_without_decision_id_skips_db(self):
        svc, mock_db, _, _ = _make_service()
        item = _make_editorial_item(decision_id="")
        svc._pending_editorial["uid-1"] = item

        svc.skip_editorial("uid-1")

        mock_db.update_email_decision.assert_not_called()

    def test_skip_nonexistent_uid_no_db_call(self):
        svc, mock_db, _, _ = _make_service()

        svc.skip_editorial("nonexistent")

        mock_db.update_email_decision.assert_not_called()
