"""HTTP contract tests — do all API endpoints accept input and return BrainResponse?

These tests verify the public HTTP surface works end-to-end through FastAPI,
with all heavy dependencies (db, brain, inbox, memory, etc.) replaced by fakes.
We test behavior, not wiring: endpoints exist, accept documented input,
return the right shape, and errors are handled gracefully.
"""
# ruff: noqa: E402

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# Patch create_brain before api.py is imported
_fake_components = MagicMock()
_fake_components.brain = MagicMock()
_fake_components.inbox = MagicMock()
_fake_components.memory = MagicMock()
_fake_components.db = MagicMock()
_fake_components.retriever = MagicMock()
_fake_components.gemini = MagicMock()

with patch("backend.wiring.create_brain", return_value=_fake_components):
    from backend.api import app

from fastapi.testclient import TestClient


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_fakes():
    """Reset all fakes before each test."""
    for comp in [_fake_components.brain, _fake_components.inbox,
                 _fake_components.memory, _fake_components.db,
                 _fake_components.retriever]:
        comp.reset_mock()


# ── Health ──────────────────────────────────────────────────────────


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# ── Brain ───────────────────────────────────────────────────────────


def test_brain_process_returns_result(client):
    _fake_components.brain.process.return_value = {"reply": "hello"}

    r = client.post("/brain/process", json={"input": "hi"})

    assert r.status_code == 200
    body = r.json()
    assert body["result"] == {"reply": "hello"}
    assert body["error"] == ""


def test_brain_command_returns_result(client):
    _fake_components.brain.process_command.return_value = {"status": "ok"}

    r = client.post("/brain/command", json={"command": "health"})

    assert r.status_code == 200
    assert r.json()["result"] == {"status": "ok"}


# ── Interact ────────────────────────────────────────────────────────


def test_interact_returns_brain_response_shape(client):
    with patch("backend.api.handle", return_value={"messages": [{"text": "hi"}]}):
        r = client.post("/interact", json={"action": "start", "payload": {}, "context": {}})

    assert r.status_code == 200
    body = r.json()
    assert "result" in body
    assert body["result"]["messages"][0]["text"] == "hi"


# ── Inbox ───────────────────────────────────────────────────────────


def test_inbox_fetch_unread_returns_list(client):
    _fake_components.inbox.fetch_unread.return_value = []

    r = client.post("/inbox/fetch-unread")

    assert r.status_code == 200
    assert r.json()["result"] == []


def test_inbox_approve_support(client):
    _fake_components.inbox.approve_support.return_value = None

    r = client.post("/inbox/approve-support", json={"uid": "123"})

    assert r.status_code == 200
    _fake_components.inbox.approve_support.assert_called_once_with("123")


def test_inbox_skip_support(client):
    r = client.post("/inbox/skip-support", json={"uid": "123"})

    assert r.status_code == 200
    _fake_components.inbox.skip_support.assert_called_once_with("123")


def test_inbox_approve_editorial(client):
    _fake_components.inbox.approve_editorial.return_value = None

    r = client.post("/inbox/approve-editorial", json={"uid": "123"})

    assert r.status_code == 200


def test_inbox_skip_editorial(client):
    r = client.post("/inbox/skip-editorial", json={"uid": "123"})

    assert r.status_code == 200


def test_inbox_pending_support_not_found(client):
    _fake_components.inbox.get_pending_support.return_value = None

    r = client.get("/inbox/pending-support/abc")

    assert r.status_code == 200
    assert r.json()["result"] is None


def test_inbox_pending_editorial_not_found(client):
    _fake_components.inbox.get_pending_editorial.return_value = None

    r = client.get("/inbox/pending-editorial/abc")

    assert r.status_code == 200
    assert r.json()["result"] is None


def test_inbox_update_and_approve_support(client):
    _fake_components.inbox.update_and_approve_support.return_value = None

    r = client.post("/inbox/update-and-approve-support", json={"uid": "123", "text": "new reply"})

    assert r.status_code == 200
    _fake_components.inbox.update_and_approve_support.assert_called_once_with("123", "new reply")


# ── Memory ──────────────────────────────────────────────────────────


def test_memory_search(client):
    _fake_components.memory.recall.return_value = "some context"

    r = client.get("/memory/search", params={"query": "test"})

    assert r.status_code == 200
    assert r.json()["result"] == "some context"


def test_memory_list(client):
    _fake_components.memory.list_knowledge.return_value = []

    r = client.get("/memory/list")

    assert r.status_code == 200
    assert r.json()["result"] == []


def test_memory_get_entry(client):
    _fake_components.memory.get_entry.return_value = {"id": "e1", "content": "test"}

    r = client.get("/memory/entry/e1")

    assert r.status_code == 200
    assert r.json()["result"]["id"] == "e1"


def test_memory_update_entry(client):
    _fake_components.memory.update_entry.return_value = "ok"

    r = client.put("/memory/entry/e1", json={"content": "updated"})

    assert r.status_code == 200
    _fake_components.memory.update_entry.assert_called_once_with("e1", "updated")


def test_memory_delete_entry(client):
    _fake_components.memory.deactivate_entry.return_value = "ok"

    r = client.delete("/memory/entry/e1")

    assert r.status_code == 200


def test_memory_list_domains(client):
    _fake_components.memory.list_domains.return_value = ["general", "tech"]

    r = client.get("/memory/domains")

    assert r.status_code == 200
    assert r.json()["result"] == ["general", "tech"]


def test_memory_list_environments(client):
    _fake_components.memory.list_environments.return_value = []

    r = client.get("/memory/environments")

    assert r.status_code == 200


def test_memory_get_environment(client):
    _fake_components.memory.get_environment.return_value = {"name": "main"}

    r = client.get("/memory/environment", params={"name": "main"})

    assert r.status_code == 200
    assert r.json()["result"]["name"] == "main"


def test_memory_create_environment(client):
    r = client.post("/memory/environment/create", json={
        "name": "test", "description": "test env"})

    assert r.status_code == 200
    _fake_components.db.save_environment.assert_called_once()


def test_memory_update_environment(client):
    _fake_components.memory.update_environment.return_value = "ok"

    r = client.put("/memory/environment/update", json={
        "name": "test", "description": "updated"})

    assert r.status_code == 200


def test_memory_bind_environment(client):
    r = client.post("/memory/environment/bind", json={"chat_id": 123, "name": "test"})

    assert r.status_code == 200
    _fake_components.db.bind_chat.assert_called_once_with(123, "test")


def test_memory_unbind_environment(client):
    r = client.post("/memory/environment/unbind", params={"chat_id": 123})

    assert r.status_code == 200
    _fake_components.db.unbind_chat.assert_called_once_with(123)


def test_memory_get_bindings(client):
    _fake_components.db.get_bindings_for_environment.return_value = [123]

    r = client.get("/memory/environment/bindings", params={"name": "test"})

    assert r.status_code == 200
    assert r.json()["result"] == [123]


# ── Permissions ─────────────────────────────────────────────────────


def test_permissions_list(client):
    _fake_components.db.list_permissions.return_value = []

    r = client.get("/permissions")

    assert r.status_code == 200


def test_permissions_grant(client):
    r = client.post("/permissions/grant", json={
        "tool_name": "search", "environment": "main", "roles": ["admin"]})

    assert r.status_code == 200
    _fake_components.db.grant.assert_called_once_with("search", "main", ["admin"])


def test_permissions_revoke(client):
    _fake_components.db.revoke.return_value = True

    r = client.post("/permissions/revoke", json={
        "tool_name": "search", "environment": "main"})

    assert r.status_code == 200
    assert r.json()["result"] == "ok"


def test_permissions_revoke_not_found(client):
    _fake_components.db.revoke.return_value = False

    r = client.post("/permissions/revoke", json={
        "tool_name": "search", "environment": "main"})

    assert r.json()["result"] == "not_found"


# ── User ────────────────────────────────────────────────────────────


def test_user_admin_telegram_ids(client):
    _fake_components.db.get_admin_telegram_ids.return_value = [111, 222]

    r = client.get("/user/admin_telegram_ids")

    assert r.status_code == 200
    assert r.json()["result"] == [111, 222]


def test_user_is_admin_true(client):
    _fake_components.db.get_user_by_telegram_id.return_value = {"role": "admin"}

    r = client.get("/user/is_admin", params={"telegram_id": 111})

    assert r.json()["result"] is True


def test_user_is_admin_false(client):
    _fake_components.db.get_user_by_telegram_id.return_value = {"role": "user"}

    r = client.get("/user/is_admin", params={"telegram_id": 222})

    assert r.json()["result"] is False


def test_user_is_admin_not_found(client):
    _fake_components.db.get_user_by_telegram_id.return_value = None

    r = client.get("/user/is_admin", params={"telegram_id": 999})

    assert r.json()["result"] is False


def test_user_context(client):
    _fake_components.db.get_user_by_telegram_id.return_value = {"id": "u1", "role": "admin"}
    _fake_components.retriever.get_user_context.return_value = "some context"

    r = client.get("/user/context", params={"telegram_id": 111})

    assert r.json()["result"] == "some context"


def test_user_context_not_found(client):
    _fake_components.db.get_user_by_telegram_id.return_value = None

    r = client.get("/user/context", params={"telegram_id": 999})

    assert r.json()["result"] == ""


def test_user_note(client):
    _fake_components.memory.remember.return_value = "entry-1"

    r = client.post("/user/u1/note", json={"text": "note text", "domain": "general"})

    assert r.status_code == 200
    assert r.json()["result"]["id"] == "entry-1"


def test_user_list(client):
    _fake_components.db.list_users.return_value = [{"id": "u1"}]

    r = client.get("/memory/users")

    assert r.status_code == 200
    assert r.json()["result"] == [{"id": "u1"}]


# ── Messages ────────────────────────────────────────────────────────


def test_message_save(client):
    _fake_components.db.save_message.return_value = "msg-1"

    r = client.post("/message/save", json={"text": "hello"})

    assert r.status_code == 200
    assert r.json()["result"]["id"] == "msg-1"


def test_message_by_telegram_id(client):
    _fake_components.db.get_by_telegram_message_id.return_value = {"id": "msg-1"}

    r = client.get("/message/by-telegram-id", params={"chat_id": 1, "telegram_message_id": 42})

    assert r.status_code == 200
    assert r.json()["result"]["id"] == "msg-1"


def test_message_update_metadata(client):
    r = client.put("/message/msg-1/metadata", json={"updates": {"key": "val"}})

    assert r.status_code == 200
    _fake_components.db.update_metadata.assert_called_once_with("msg-1", {"key": "val"})


# ── Scrape ──────────────────────────────────────────────────────────


def test_scrape_list_environments(client):
    _fake_components.db.list_scrapable_environments.return_value = [{"name": "chan1"}]

    r = client.get("/scrape/environments")

    assert r.status_code == 200
    assert r.json()["result"] == [{"name": "chan1"}]


# ── Admin feedback ──────────────────────────────────────────────────


def test_store_feedback(client):
    _fake_components.memory.remember.return_value = "entry-1"

    r = client.post("/admin/store-feedback", json={"text": "good job", "domain": "general"})

    assert r.status_code == 200
    assert r.json()["result"] == "ok"


# ── Error handling ──────────────────────────────────────────────────


def test_unhandled_exception_returns_error_json():
    _fake_components.brain.process.side_effect = RuntimeError("boom")

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.post("/brain/process", json={"input": "hi"})

    _fake_components.brain.process.side_effect = None
    body = r.json()
    assert body["result"] is None
    assert "boom" in body["error"]


def test_validation_error_returns_422(client):
    r = client.post("/brain/process", json={})

    assert r.status_code == 422
