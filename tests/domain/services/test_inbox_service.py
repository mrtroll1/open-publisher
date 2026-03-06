"""Tests for InboxService: process/classify routing + decision tracking."""

from unittest.mock import patch

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


@patch("backend.commands.inbox_service.DbGateway")
@patch("backend.commands.inbox_service.EmailGateway")
@patch("backend.commands.inbox_service.GeminiGateway")
@patch("backend.commands.inbox_service.TechSupportHandler")
def _make_service(MockTSH, MockGemini, MockEmail, MockDb):
    from backend.commands.inbox_service import InboxService
    svc = InboxService()
    return svc, svc._db, svc._email_gw, svc._tech_support, svc._gemini


# ===================================================================
#  approve_support — decision tracking
# ===================================================================

class TestApproveSupportDecision:

    def test_approve_updates_decision_approved(self):
        svc, mock_db, mock_email, mock_tsh, _ = _make_service()
        draft = _make_draft(decision_id="dec-support-1")
        svc._pending_support["uid-1"] = draft

        result = svc.approve_support("uid-1")

        assert result is draft
        mock_db.update_email_decision_output.assert_called_once_with("dec-support-1", draft.draft_reply)
        mock_db.update_email_decision.assert_called_once_with("dec-support-1", "APPROVED", decided_by="admin")

    def test_approve_without_decision_id_skips_db(self):
        svc, mock_db, mock_email, mock_tsh, _ = _make_service()
        draft = _make_draft(decision_id="")
        svc._pending_support["uid-1"] = draft

        svc.approve_support("uid-1")

        mock_db.update_email_decision_output.assert_not_called()
        mock_db.update_email_decision.assert_not_called()

    def test_approve_sends_email_and_marks_read(self):
        svc, mock_db, mock_email, mock_tsh, _ = _make_service()
        email = _make_email()
        draft = _make_draft(email=email)
        svc._pending_support["uid-1"] = draft

        svc.approve_support("uid-1")

        mock_email.send_reply.assert_called_once()
        mock_email.mark_read.assert_called_once_with("uid-1")

    def test_approve_nonexistent_uid_returns_none(self):
        svc, mock_db, _, _, _ = _make_service()

        result = svc.approve_support("nonexistent")

        assert result is None
        mock_db.update_email_decision.assert_not_called()


# ===================================================================
#  skip_support — decision tracking + discard
# ===================================================================

class TestSkipSupportDecision:

    def test_skip_updates_decision_rejected(self):
        svc, mock_db, _, mock_tsh, _ = _make_service()
        draft = _make_draft(decision_id="dec-support-2")
        svc._pending_support["uid-1"] = draft

        svc.skip_support("uid-1")

        mock_db.update_email_decision.assert_called_once_with("dec-support-2", "REJECTED", decided_by="admin")

    def test_skip_calls_discard_with_draft(self):
        svc, mock_db, _, mock_tsh, _ = _make_service()
        draft = _make_draft(decision_id="dec-support-2")
        svc._pending_support["uid-1"] = draft

        svc.skip_support("uid-1")

        mock_tsh.discard.assert_called_once_with("uid-1", draft=draft)

    def test_skip_without_decision_id_skips_db(self):
        svc, mock_db, _, mock_tsh, _ = _make_service()
        draft = _make_draft(decision_id="")
        svc._pending_support["uid-1"] = draft

        svc.skip_support("uid-1")

        mock_db.update_email_decision.assert_not_called()
        mock_tsh.discard.assert_called_once()

    def test_skip_nonexistent_uid_still_discards(self):
        svc, mock_db, _, mock_tsh, _ = _make_service()

        svc.skip_support("nonexistent")

        mock_db.update_email_decision.assert_not_called()
        mock_tsh.discard.assert_called_once_with("nonexistent", draft=None)


# ===================================================================
#  approve_editorial — decision tracking
# ===================================================================

class TestApproveEditorialDecision:

    @patch("backend.commands.inbox_service.CHIEF_EDITOR_EMAIL", "editor@test.com")
    def test_approve_updates_decision_approved(self):
        svc, mock_db, mock_email, _, _ = _make_service()
        item = _make_editorial_item(decision_id="dec-edit-1")
        svc._pending_editorial["uid-1"] = item

        result = svc.approve_editorial("uid-1")

        assert result is item
        mock_db.update_email_decision.assert_called_once_with("dec-edit-1", "APPROVED", decided_by="admin")

    @patch("backend.commands.inbox_service.CHIEF_EDITOR_EMAIL", "editor@test.com")
    def test_approve_without_decision_id_skips_db(self):
        svc, mock_db, mock_email, _, _ = _make_service()
        item = _make_editorial_item(decision_id="")
        svc._pending_editorial["uid-1"] = item

        svc.approve_editorial("uid-1")

        mock_db.update_email_decision.assert_not_called()

    def test_approve_nonexistent_uid_returns_none(self):
        svc, mock_db, _, _, _ = _make_service()

        result = svc.approve_editorial("nonexistent")

        assert result is None
        mock_db.update_email_decision.assert_not_called()


# ===================================================================
#  skip_editorial — decision tracking
# ===================================================================

class TestSkipEditorialDecision:

    def test_skip_updates_decision_rejected(self):
        svc, mock_db, _, _, _ = _make_service()
        item = _make_editorial_item(decision_id="dec-edit-2")
        svc._pending_editorial["uid-1"] = item

        svc.skip_editorial("uid-1")

        mock_db.update_email_decision.assert_called_once_with("dec-edit-2", "REJECTED", decided_by="admin")

    def test_skip_without_decision_id_skips_db(self):
        svc, mock_db, _, _, _ = _make_service()
        item = _make_editorial_item(decision_id="")
        svc._pending_editorial["uid-1"] = item

        svc.skip_editorial("uid-1")

        mock_db.update_email_decision.assert_not_called()

    def test_skip_nonexistent_uid_no_db_call(self):
        svc, mock_db, _, _, _ = _make_service()

        svc.skip_editorial("nonexistent")

        mock_db.update_email_decision.assert_not_called()


# ===================================================================
#  process() — routing by classification
# ===================================================================

class TestInboxServiceProcess:

    @patch("backend.commands.inbox_service.SUPPORT_ADDRESSES", ["support@republic.ru"])
    def test_process_routes_to_support_when_classify_returns_tech_support(self):
        svc, mock_db, _, mock_tsh, _ = _make_service()
        email = _make_email(to_addr="support@republic.ru")
        mock_tsh.draft_reply.return_value = SupportDraft(
            email=email, can_answer=True, draft_reply="Reply",
        )
        mock_db.create_email_decision.return_value = "dec-1"

        result = svc.process(email)

        assert result is not None
        assert result.category == "tech_support"
        assert result.draft is not None
        assert result.draft.draft_reply == "Reply"
        mock_tsh.draft_reply.assert_called_once_with(email)

    @patch("backend.commands.inbox_service.CHIEF_EDITOR_EMAIL", "editor@test.com")
    @patch("backend.commands.inbox_service.EMAIL_ADDRESS", "inbox@republic.ru")
    @patch("backend.commands.inbox_service.SUPPORT_ADDRESSES", [])
    def test_process_routes_to_editorial_when_classify_returns_editorial(self):
        svc, mock_db, _, _, mock_gemini = _make_service()
        email = _make_email(to_addr="inbox@republic.ru")
        # LLM classify returns editorial
        mock_gemini.call.side_effect = [
            {"category": "editorial"},  # _llm_classify
            {"forward": True, "reply": "Thanks"},  # editorial_assess
        ]
        mock_db.create_email_decision.return_value = "dec-2"

        result = svc.process(email)

        assert result is not None
        assert result.category == "editorial"
        assert result.editorial is not None
        assert result.editorial.reply_to_sender == "Thanks"

    @patch("backend.commands.inbox_service.EMAIL_ADDRESS", "inbox@republic.ru")
    @patch("backend.commands.inbox_service.SUPPORT_ADDRESSES", [])
    def test_process_returns_none_when_classify_returns_ignore(self):
        svc, _, _, _, mock_gemini = _make_service()
        email = _make_email(to_addr="inbox@republic.ru")
        mock_gemini.call.return_value = {"category": "ignore"}

        result = svc.process(email)

        assert result is None


# ===================================================================
#  _classify() — direct address match vs LLM fallback
# ===================================================================

class TestInboxServiceClassify:

    @patch("backend.commands.inbox_service.SUPPORT_ADDRESSES", ["support@republic.ru"])
    def test_classify_support_addr_skips_llm(self):
        svc, _, _, _, mock_gemini = _make_service()
        email = _make_email(to_addr="support@republic.ru")

        result = svc._classify(email)

        assert result == "tech_support"
        mock_gemini.call.assert_not_called()

    @patch("backend.commands.inbox_service.EMAIL_ADDRESS", "inbox@republic.ru")
    @patch("backend.commands.inbox_service.SUPPORT_ADDRESSES", [])
    def test_classify_falls_back_to_llm_when_no_direct_match(self):
        svc, _, _, _, mock_gemini = _make_service()
        email = _make_email(to_addr="inbox@republic.ru")
        mock_gemini.call.return_value = {"category": "editorial"}

        result = svc._classify(email)

        assert result == "editorial"
        mock_gemini.call.assert_called_once()

    @patch("backend.commands.inbox_service.EMAIL_ADDRESS", "inbox@republic.ru")
    @patch("backend.commands.inbox_service.SUPPORT_ADDRESSES", [])
    def test_classify_unknown_addr_returns_ignore(self):
        svc, _, _, _, mock_gemini = _make_service()
        email = _make_email(to_addr="random@somewhere.com")

        result = svc._classify(email)

        assert result == "ignore"
        mock_gemini.call.assert_not_called()


# ===================================================================
#  _handle_support() — draft creation + decision_id
# ===================================================================

class TestHandleSupport:

    @patch("backend.commands.inbox_service.SUPPORT_ADDRESSES", ["support@republic.ru"])
    def test_creates_support_draft_with_decision_id(self):
        svc, mock_db, _, mock_tsh, _ = _make_service()
        email = _make_email(uid="uid-s1")
        draft = SupportDraft(email=email, can_answer=True, draft_reply="Draft reply")
        mock_tsh.draft_reply.return_value = draft
        mock_db.create_email_decision.return_value = "dec-support-new"

        result = svc._handle_support(email)

        assert result is not None
        assert result.category == "tech_support"
        assert result.uid == "uid-s1"
        assert result.draft.decision_id == "dec-support-new"
        assert result.draft.draft_reply == "Draft reply"
        mock_db.create_email_decision.assert_called_once_with(
            task="SUPPORT_ANSWER", channel="EMAIL",
            input_message_ids=["<msg-1>"],
        )

    def test_duplicate_uid_returns_none(self):
        svc, mock_db, _, mock_tsh, _ = _make_service()
        email = _make_email(uid="uid-dup")
        svc._pending_support["uid-dup"] = _make_draft()

        result = svc._handle_support(email)

        assert result is None
        mock_tsh.draft_reply.assert_not_called()


# ===================================================================
#  _handle_editorial() — LLM assess + editorial item creation
# ===================================================================

class TestHandleEditorial:

    @patch("backend.commands.inbox_service.CHIEF_EDITOR_EMAIL", "editor@test.com")
    def test_creates_editorial_item_when_forward_true(self):
        svc, mock_db, _, _, mock_gemini = _make_service()
        email = _make_email(uid="uid-e1")
        mock_gemini.call.return_value = {"forward": True, "reply": "We'll review it"}
        mock_db.create_email_decision.return_value = "dec-edit-new"

        result = svc._handle_editorial(email)

        assert result is not None
        assert result.category == "editorial"
        assert result.uid == "uid-e1"
        assert result.editorial.reply_to_sender == "We'll review it"
        assert result.editorial.decision_id == "dec-edit-new"

    @patch("backend.commands.inbox_service.CHIEF_EDITOR_EMAIL", "editor@test.com")
    def test_returns_none_when_forward_false(self):
        svc, mock_db, _, _, mock_gemini = _make_service()
        email = _make_email(uid="uid-e2")
        mock_gemini.call.return_value = {"forward": False}

        result = svc._handle_editorial(email)

        assert result is None
        mock_db.create_email_decision.assert_not_called()

    @patch("backend.commands.inbox_service.CHIEF_EDITOR_EMAIL", "")
    def test_returns_none_when_no_chief_editor_email(self):
        svc, mock_db, _, _, mock_gemini = _make_service()
        email = _make_email(uid="uid-e3")

        result = svc._handle_editorial(email)

        assert result is None
        mock_gemini.call.assert_not_called()
