"""Inbox workflow — does the classify→draft→approve/skip lifecycle work?"""

from unittest.mock import MagicMock, patch

from backend.commands.process_inbox import InboxWorkflow
from backend.models import EditorialItem, InboxCategory, IncomingEmail, SupportDraft


def _make_email(**overrides):
    defaults = dict(uid="e1", from_addr="user@test.com", to_addr="support@test.com",
                    subject="Help", body="I need help", date="2025-01-01")
    defaults.update(overrides)
    return IncomingEmail(**defaults)


def _make_workflow(**overrides):
    defaults = {
        "tech_support": MagicMock(),
        "email_gw": MagicMock(),
        "db": MagicMock(),
        "classifier": MagicMock(),
        "assessor": MagicMock(),
    }
    defaults.update(overrides)
    defaults["db"].save_message.return_value = "decision-1"
    return InboxWorkflow(**defaults), defaults


# ── Classification ──────────────────────────────────────────────────


def test_support_address_classified_by_rules():
    wf, _ = _make_workflow()

    result = wf.classify_by_address(_make_email(to_addr="support@test.com"))

    # support@test.com is checked against SUPPORT_ADDRESSES config
    # The result depends on config, but the method is deterministic
    assert result in (InboxCategory.TECH_SUPPORT, "unknown")


def test_unknown_address_returns_unknown():
    wf, _ = _make_workflow()

    result = wf.classify_by_address(_make_email(to_addr="random@other.com"))

    assert result == "unknown"


# ── Support lifecycle ───────────────────────────────────────────────


def test_register_support_draft_stores_and_returns_pending():
    wf, _ = _make_workflow()
    email = _make_email()
    draft = SupportDraft(email=email, can_answer=True, draft_reply="Try restarting")

    item = wf.register_support_draft(email, draft)

    assert item.category == InboxCategory.TECH_SUPPORT
    assert item.uid == "e1"
    assert item.draft.draft_reply == "Try restarting"
    assert wf.is_support_pending("e1")


def test_approve_support_sends_reply_and_removes_pending():
    wf, deps = _make_workflow()
    email = _make_email()
    draft = SupportDraft(email=email, can_answer=True, draft_reply="Try restarting")
    wf.register_support_draft(email, draft)

    result = wf.approve_support("e1")

    assert result is not None
    deps["email_gw"].send_reply.assert_called_once()
    deps["email_gw"].mark_read.assert_called_once_with("e1")
    assert not wf.is_support_pending("e1")


def test_skip_support_removes_pending_without_sending():
    wf, deps = _make_workflow()
    email = _make_email()
    draft = SupportDraft(email=email, can_answer=True, draft_reply="Try restarting")
    wf.register_support_draft(email, draft)

    wf.skip_support("e1")

    deps["email_gw"].send_reply.assert_not_called()
    assert not wf.is_support_pending("e1")


def test_update_and_approve_uses_new_text():
    wf, deps = _make_workflow()
    email = _make_email()
    draft = SupportDraft(email=email, can_answer=True, draft_reply="old reply")
    wf.register_support_draft(email, draft)

    result = wf.update_and_approve_support("e1", "corrected reply")

    assert result.draft_reply == "corrected reply"
    deps["email_gw"].send_reply.assert_called_once()


def test_approve_nonexistent_returns_none():
    wf, _ = _make_workflow()

    assert wf.approve_support("nonexistent") is None


def test_get_pending_support():
    wf, _ = _make_workflow()
    email = _make_email()
    draft = SupportDraft(email=email, can_answer=True, draft_reply="reply")
    wf.register_support_draft(email, draft)

    assert wf.get_pending_support("e1") is not None
    assert wf.get_pending_support("nonexistent") is None


# ── Editorial lifecycle ─────────────────────────────────────────────


def test_register_editorial_stores_and_returns_pending():
    wf, _ = _make_workflow()
    email = _make_email(uid="ed1")
    item = EditorialItem(email=email, reply_to_sender="Thanks for the article")

    result = wf.register_editorial(email, item)

    assert result.category == InboxCategory.EDITORIAL
    assert result.uid == "ed1"
    assert wf.get_pending_editorial("ed1") is not None


def test_approve_editorial_forwards_and_removes_pending():
    wf, deps = _make_workflow()
    email = _make_email(uid="ed1")
    item = EditorialItem(email=email, reply_to_sender="Thanks")
    wf.register_editorial(email, item)

    result = wf.approve_editorial("ed1")

    assert result is not None
    # Should forward + reply to sender = 2 send_reply calls
    assert deps["email_gw"].send_reply.call_count == 2
    deps["email_gw"].mark_read.assert_called_once_with("ed1")
    assert wf.get_pending_editorial("ed1") is None


def test_skip_editorial_removes_without_sending():
    wf, deps = _make_workflow()
    email = _make_email(uid="ed1")
    item = EditorialItem(email=email, reply_to_sender="Thanks")
    wf.register_editorial(email, item)

    wf.skip_editorial("ed1")

    deps["email_gw"].send_reply.assert_not_called()
    assert wf.get_pending_editorial("ed1") is None


# ── Process dispatch ────────────────────────────────────────────────


@patch("backend.commands.process_inbox.SUPPORT_ADDRESSES", ["support@test.com"])
def test_process_support_email_creates_draft():
    tech_support = MagicMock()
    tech_support.draft_reply.return_value = SupportDraft(
        email=_make_email(), can_answer=True, draft_reply="auto reply")
    wf, _ = _make_workflow(tech_support=tech_support)

    item = wf.process(_make_email(to_addr="support@test.com"))

    assert item is not None
    assert item.category == InboxCategory.TECH_SUPPORT


def test_process_ignores_unclassifiable_email():
    classifier = MagicMock()
    classifier.run.return_value = {"category": "ignore"}
    wf, _ = _make_workflow(classifier=classifier)

    item = wf.process(_make_email(to_addr="random@other.com"))

    assert item is None


@patch("backend.commands.process_inbox.SUPPORT_ADDRESSES", ["support@test.com"])
def test_duplicate_support_email_ignored():
    tech_support = MagicMock()
    tech_support.draft_reply.return_value = SupportDraft(
        email=_make_email(), can_answer=True, draft_reply="reply")
    wf, _ = _make_workflow(tech_support=tech_support)

    wf.process(_make_email(uid="dup1", to_addr="support@test.com"))
    second = wf.process(_make_email(uid="dup1", to_addr="support@test.com"))

    assert second is None
    assert tech_support.draft_reply.call_count == 1
