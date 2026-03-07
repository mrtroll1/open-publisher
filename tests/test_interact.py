"""Interact dispatch — does the contract with the bot hold?"""

from unittest.mock import patch

from backend.interact import handle
from backend.interact.helpers import InteractContext

# ── Dispatch ─────────────────────────────────────────────────────────


def test_unknown_action_returns_error():
    result = handle("totally_fake", {}, {"user_id": 1})

    assert len(result["messages"]) == 1
    assert "Неизвестное действие" in result["messages"][0]["text"]


# ── Response shape ───────────────────────────────────────────────────


def test_start_admin_response_shape():
    result = handle("start", {}, {"user_id": 1, "is_admin": True})

    assert "messages" in result
    assert isinstance(result["messages"], list)
    assert len(result["messages"]) >= 1
    assert "text" in result["messages"][0]
    # start clears FSM
    assert result.get("fsm_state") is None


def test_start_contractor_response_shape():
    result = handle("start", {}, {"user_id": 1, "is_admin": False})

    assert "messages" in result
    assert result.get("fsm_state") is None


# ── FSM transitions ─────────────────────────────────────────────────


@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id", return_value=None)
@patch("backend.interact.contractor.fuzzy_find", return_value=[])
def test_free_text_unknown_user_starts_registration(*_):
    result = handle("free_text", {"text": "John Doe"}, {"user_id": 999})

    assert result.get("fsm_state") == "waiting_type"
    assert result.get("fsm_data", {}).get("alias") == "John Doe"


@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id", return_value=None)
@patch("backend.interact.contractor.fuzzy_find")
def test_free_text_fuzzy_match_shows_suggestions(mock_fuzzy, *_):
    from unittest.mock import MagicMock
    fake_contractor = MagicMock()
    fake_contractor.id = "c1"
    fake_contractor.display_name = "John Doe"
    fake_contractor.aliases = []
    mock_fuzzy.return_value = [(fake_contractor, 0.9)]

    result = handle("free_text", {"text": "Jon Doe"}, {"user_id": 999})

    # Should show suggestion buttons, not start registration
    assert result.get("fsm_state") is None or "waiting_type" not in str(result.get("fsm_state"))
    assert any("keyboard" in m for m in result["messages"])


@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id")
def test_free_text_known_user_gets_menu(mock_find, *_):
    from unittest.mock import MagicMock
    fake_contractor = MagicMock()
    fake_contractor.role_code = "author"
    mock_find.return_value = fake_contractor

    result = handle("free_text", {"text": "anything"}, {"user_id": 42})

    # Known user → menu, FSM cleared
    assert result.get("fsm_state") is None
    assert any("keyboard" in m for m in result["messages"])


def test_type_selection_valid():
    result = handle("type_selection", {"text": "1"}, {"user_id": 1, "fsm_data": {"alias": "Test"}})

    assert result.get("fsm_state") == "waiting_data"
    assert result["fsm_data"]["contractor_type"] == "самозанятый"


def test_type_selection_invalid():
    result = handle("type_selection", {"text": "banana"}, {"user_id": 1, "fsm_data": {}})

    # Should stay in same state, ask again
    assert "fsm_state" not in result  # no state change
    assert "1, 2 или 3" in result["messages"][0]["text"]


# ── Verification flow ───────────────────────────────────────────────


@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_id")
def test_verification_wrong_code_tracks_attempts(mock_find, *_):
    from unittest.mock import MagicMock
    c = MagicMock()
    c.secret_code = "ABC123"
    mock_find.return_value = c

    ctx: InteractContext = {
        "user_id": 1,
        "fsm_data": {"pending_contractor_id": "c1", "verification_attempts": 0},
    }
    result = handle("verification_code", {"text": "WRONG"}, ctx)

    assert result["fsm_data"]["verification_attempts"] == 1
    assert "Неверный код" in result["messages"][0]["text"]


@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_id")
def test_verification_max_attempts_locks_out(mock_find, *_):
    from unittest.mock import MagicMock
    c = MagicMock()
    c.secret_code = "ABC123"
    mock_find.return_value = c

    ctx: InteractContext = {
        "user_id": 1,
        "fsm_data": {"pending_contractor_id": "c1", "verification_attempts": 2},
    }
    result = handle("verification_code", {"text": "WRONG"}, ctx)

    # Should lock out — clear FSM
    assert result.get("fsm_state") is None
    assert "Превышено" in result["messages"][0]["text"]


# ── Handler errors don't crash ───────────────────────────────────────


@patch("backend.interact.contractor.load_all_contractors", side_effect=RuntimeError("db down"))
def test_handler_exception_returns_error_message(*_):
    result = handle("free_text", {"text": "hello"}, {"user_id": 1})

    assert "Ошибка" in result["messages"][0]["text"]
