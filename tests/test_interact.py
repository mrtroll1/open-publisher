"""Interact dispatch — does the contract with the bot hold?"""

from unittest.mock import MagicMock, patch

from backend.interact import handle
from backend.interact.helpers import InteractContext
from backend.models import ContractorType, Currency, Invoice, InvoiceStatus, RoleCode, SamozanyatyContractor

# ── Helpers ──────────────────────────────────────────────────────────


def _has_keyboard(result):
    return any("keyboard" in m for m in result["messages"])


def _make_samozanyaty(tid="42"):
    return SamozanyatyContractor(
        id="c1", aliases=[], role_code=RoleCode.AUTHOR, is_photographer=False,
        email="t@x.com", bank_name="Bank", bank_account="123", mags="",
        invoice_number=1, telegram=tid, secret_code="ABC",
        name_ru="Тест", address="Addr", passport_series="1234",
        passport_number="567890", inn="123456789012", bik="044525225",
        corr_account="30101810400000000225",
    )


def _make_contractor(**overrides):
    c = MagicMock()
    c.id = overrides.get("id", "c1")
    c.display_name = overrides.get("display_name", "Test")
    c.role_code = overrides.get("role_code", RoleCode.AUTHOR)
    c.aliases = overrides.get("aliases", [])
    c.is_stub = overrides.get("is_stub", False)
    c.telegram = overrides.get("telegram")
    c.secret_code = overrides.get("secret_code", "ABC123")
    c.type = overrides.get("type", ContractorType.SAMOZANYATY)
    c.currency = overrides.get("currency", Currency.RUB)
    for k, v in overrides.items():
        setattr(c, k, v)
    return c


# ── Dispatch ─────────────────────────────────────────────────────────


def test_unknown_action_returns_error():
    result = handle("totally_fake", {}, {"user_id": 1})

    assert len(result["messages"]) == 1


# ── Start ────────────────────────────────────────────────────────────


def test_start_admin_clears_fsm():
    result = handle("start", {}, {"user_id": 1, "is_admin": True})

    assert result.get("fsm_state") is None
    assert result["messages"] == []


def test_start_non_admin_shows_welcome_with_button():
    result = handle("start", {}, {"user_id": 1, "is_admin": False})

    assert result.get("fsm_state") is None
    assert len(result["messages"]) == 1
    keyboard = result["messages"][0]["keyboard"]
    flat = [btn["data"] for row in keyboard for btn in row]
    assert "start:contractor" in flat


# ── Start callback ───────────────────────────────────────────────────


@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id")
def test_start_callback_returning_contractor_shows_menu(mock_find, *_):
    mock_find.return_value = _make_contractor()

    result = handle("start_callback", {}, {"user_id": 42})

    assert result.get("fsm_state") is None
    assert _has_keyboard(result)


@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id", return_value=None)
def test_start_callback_new_user_starts_registration(*_):
    result = handle("start_callback", {}, {"user_id": 999})

    assert result.get("fsm_state") == "lookup"
    assert len(result["messages"]) >= 1


# ── Menu ─────────────────────────────────────────────────────────────


@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id")
def test_menu_known_contractor_shows_keyboard(mock_find, *_):
    mock_find.return_value = _make_contractor()

    result = handle("menu", {}, {"user_id": 42})

    assert result.get("fsm_state") is None
    assert _has_keyboard(result)


@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id", return_value=None)
def test_menu_non_contractor_rejects(*_):
    result = handle("menu", {}, {"user_id": 999})

    assert len(result["messages"]) == 1
    assert not _has_keyboard(result)


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
    mock_fuzzy.return_value = [(_make_contractor(), 0.9)]

    result = handle("free_text", {"text": "Jon Doe"}, {"user_id": 999})

    assert result.get("fsm_state") != "waiting_type"
    assert _has_keyboard(result)


@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id")
def test_free_text_known_user_gets_menu(mock_find, *_):
    mock_find.return_value = _make_contractor()

    result = handle("free_text", {"text": "anything"}, {"user_id": 42})

    assert result.get("fsm_state") is None
    assert _has_keyboard(result)


def test_type_selection_valid():
    result = handle("type_selection", {"text": "1"}, {"user_id": 1, "fsm_data": {"alias": "Test"}})

    assert result.get("fsm_state") == "waiting_data"
    assert result["fsm_data"]["contractor_type"] == "самозанятый"


def test_type_selection_invalid():
    result = handle("type_selection", {"text": "banana"}, {"user_id": 1, "fsm_data": {}})

    assert "fsm_state" not in result
    assert len(result["messages"]) == 1


# ── Verification flow ───────────────────────────────────────────────


@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_id")
def test_verification_wrong_code_tracks_attempts(mock_find, *_):
    mock_find.return_value = _make_contractor()

    ctx: InteractContext = {
        "user_id": 1,
        "fsm_data": {"pending_contractor_id": "c1", "verification_attempts": 0},
    }
    result = handle("verification_code", {"text": "WRONG"}, ctx)

    assert result["fsm_data"]["verification_attempts"] == 1


@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_id")
def test_verification_max_attempts_locks_out(mock_find, *_):
    mock_find.return_value = _make_contractor()

    ctx: InteractContext = {
        "user_id": 1,
        "fsm_data": {"pending_contractor_id": "c1", "verification_attempts": 2},
    }
    result = handle("verification_code", {"text": "WRONG"}, ctx)

    assert result.get("fsm_state") is None


@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_id")
@patch("backend.interact.contractor.bind_telegram_id")
def test_verification_correct_code_binds(mock_bind, mock_find, *_):
    mock_find.return_value = _make_contractor()

    ctx: InteractContext = {
        "user_id": 42,
        "fsm_data": {"pending_contractor_id": "c1", "verification_attempts": 0},
    }
    result = handle("verification_code", {"text": "abc123"}, ctx)

    assert result.get("fsm_state") is None
    mock_bind.assert_called_once_with("c1", 42)


@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_id")
@patch("backend.interact.contractor.bind_telegram_id")
def test_stub_verification_starts_type_selection(mock_bind, mock_find, *_):
    mock_find.return_value = _make_contractor(is_stub=True)

    ctx: InteractContext = {
        "user_id": 42,
        "fsm_data": {"pending_contractor_id": "c1", "verification_attempts": 0},
    }
    result = handle("verification_code", {"text": "abc123"}, ctx)

    assert result.get("fsm_state") == "waiting_type"
    assert result["fsm_data"]["claiming_stub_id"] == "c1"
    mock_bind.assert_called_once_with("c1", 42)


@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_id")
@patch("backend.interact.contractor.bind_telegram_id")
def test_non_stub_verification_goes_to_menu(mock_bind, mock_find, *_):
    mock_find.return_value = _make_contractor()

    ctx: InteractContext = {
        "user_id": 42,
        "fsm_data": {"pending_contractor_id": "c1", "verification_attempts": 0},
    }
    result = handle("verification_code", {"text": "abc123"}, ctx)

    assert result.get("fsm_state") is None
    assert _has_keyboard(result)
    mock_bind.assert_called_once_with("c1", 42)


# ── Handler errors don't crash ───────────────────────────────────────


@patch("backend.interact.contractor.load_all_contractors", side_effect=RuntimeError("db down"))
def test_handler_exception_returns_error_message(*_):
    result = handle("free_text", {"text": "hello"}, {"user_id": 1})

    assert len(result["messages"]) == 1


# ── Data input ───────────────────────────────────────────────────────


@patch("backend.interact.contractor.RegistrationParser")
def test_data_input_parse_error_shows_retry(mock_parser_cls):
    mock_parser_cls.return_value.parse.return_value = {"parse_error": "bad"}

    ctx = {"user_id": 1, "fsm_data": {"contractor_type": "самозанятый", "collected_data": {}}}
    result = handle("data_input", {"text": "garbage"}, ctx)

    assert len(result["messages"]) == 1


@patch("backend.interact.contractor.validate_contractor_fields", return_value=[])
@patch("backend.interact.contractor.RegistrationParser")
@patch("backend.interact.contractor.ContractorFactory")
@patch("backend.interact.contractor.CONTRACTOR_CLASS_BY_TYPE")
def test_data_input_missing_fields_shows_progress(mock_types, mock_factory_cls, mock_parser_cls, _validate):
    mock_parser_cls.return_value.parse.return_value = {"name": "Тест"}
    mock_cls = MagicMock()
    mock_cls.required_fields.return_value = {"name": "ФИО", "inn": "ИНН"}
    mock_cls.all_field_labels.return_value = {"name": "ФИО", "inn": "ИНН"}
    mock_types.__getitem__ = lambda _self, _key: mock_cls
    mock_factory_cls.return_value.check_complete.return_value = (False, {"inn": "ИНН"})

    ctx = {"user_id": 1, "fsm_data": {"contractor_type": "самозанятый", "collected_data": {}}}
    result = handle("data_input", {"text": "Тест"}, ctx)

    assert result["messages"][0]["data"]["type"].value == "registration_progress"


# ── Sign doc ─────────────────────────────────────────────────────────


@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id", return_value=None)
def test_sign_doc_non_contractor_rejects(*_):
    result = handle("sign_doc", {}, {"user_id": 999})

    assert result.get("fsm_state") is None
    assert len(result["messages"]) == 1
    assert not _has_keyboard(result)


@patch("backend.interact.contractor.InvoiceService")
@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id")
def test_sign_doc_no_invoice_no_publications(mock_find, _, mock_svc_cls):
    mock_find.return_value = _make_contractor()
    svc = mock_svc_cls.return_value
    svc.resolve_existing.return_value = None
    svc.prepare_new_data.return_value = None

    result = handle("sign_doc", {}, {"user_id": 42})

    assert len(result["messages"]) >= 1


# ── Amount input ─────────────────────────────────────────────────────


@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_id", return_value=None)
def test_amount_input_no_contractor(*_):
    ctx = {"user_id": 1, "fsm_data": {"invoice_contractor_id": "c1"}}
    result = handle("amount_input", {"text": "1000"}, ctx)

    assert result.get("fsm_state") is None


@patch("backend.interact.contractor.update_invoice_status")
@patch("backend.interact.contractor.GenerateInvoice")
@patch("backend.interact.contractor.RepublicGateway")
@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_id")
def test_amount_input_ok_generates_invoice(mock_find, _, mock_gw, mock_gen, mock_status):
    mock_find.return_value = _make_contractor(currency=Currency.EUR)
    mock_gw.return_value.fetch_articles.return_value = []
    mock_result = MagicMock()
    mock_result.pdf_bytes = b"pdf"
    mock_result.invoice.contractor_id = "c1"
    mock_gen.return_value.create_and_save.return_value = mock_result

    ctx = {"user_id": 1, "fsm_data": {
        "invoice_contractor_id": "c1", "invoice_month": "2025-02",
        "invoice_default_amount": 1000}}
    result = handle("amount_input", {"text": "ок"}, ctx)

    assert result.get("fsm_state") is None
    mock_gen.return_value.create_and_save.assert_called_once()


def test_amount_input_invalid_text():
    ctx = {"user_id": 1, "fsm_data": {
        "invoice_contractor_id": "c1", "invoice_default_amount": 1000}}

    @patch("backend.interact.contractor.load_all_contractors", return_value=[])
    @patch("backend.interact.contractor.find_contractor_by_id")
    def inner(mock_find, *_):
        mock_find.return_value = _make_contractor()
        return handle("amount_input", {"text": "abc"}, ctx)

    result = inner()
    assert len(result["messages"]) == 1
    assert "fsm_state" not in result  # stays in same state


# ── Update payment data ─────────────────────────────────────────────


@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id")
def test_update_payment_data_starts_flow(mock_find, *_):
    mock_find.return_value = _make_contractor()

    result = handle("update_payment_data", {}, {"user_id": 42})

    assert result.get("fsm_state") == "waiting_update_data"


@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id", return_value=None)
def test_update_payment_data_non_contractor_rejects(*_):
    result = handle("update_payment_data", {}, {"user_id": 999})

    assert result.get("fsm_state") is None
    assert not _has_keyboard(result)


# ── Update data ──────────────────────────────────────────────────────


def test_update_data_cancel():
    result = handle("update_data", {"text": "отмена"}, {"user_id": 1})

    assert result.get("fsm_state") is None


@patch("backend.interact.contractor.update_contractor_fields")
@patch("backend.interact.contractor.RegistrationParser")
@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id")
def test_update_data_applies_changes(mock_find, _, mock_parser_cls, mock_update):
    c = _make_contractor()
    c.type = ContractorType.SAMOZANYATY
    mock_find.return_value = c
    mock_parser_cls.return_value.parse.return_value = {"email": "new@x.com"}

    result = handle("update_data", {"text": "email new@x.com"}, {"user_id": 42})

    assert result.get("fsm_state") is None
    mock_update.assert_called_once()


# ── Manage redirects ─────────────────────────────────────────────────


@patch("backend.interact.contractor.find_redirect_rules_by_target", return_value=[])
@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id")
def test_manage_redirects_shows_editor_sources(mock_find, *_):
    mock_find.return_value = _make_contractor(role_code=RoleCode.REDAKTOR)

    result = handle("manage_redirects", {}, {"user_id": 42})

    assert _has_keyboard(result)


@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id")
def test_manage_redirects_non_editor_rejects(mock_find, *_):
    mock_find.return_value = _make_contractor(role_code=RoleCode.AUTHOR)

    result = handle("manage_redirects", {}, {"user_id": 42})

    assert not _has_keyboard(result)


# ── Editor source name ───────────────────────────────────────────────


def test_editor_source_name_cancel():
    result = handle("editor_source_name", {"text": "отмена"}, {"user_id": 1})

    assert result.get("fsm_state") is None


@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id")
def test_editor_source_name_no_match_offers_buttons(mock_find, *_):
    mock_find.return_value = _make_contractor()

    result = handle("editor_source_name", {"text": "Автор Тест"}, {"user_id": 42})

    assert result.get("fsm_data", {}).get("pending_source_name") == "Автор Тест"
    assert _has_keyboard(result)


@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id")
@patch("backend.interact.contractor.fuzzy_find")
def test_editor_source_name_shows_suggestions(mock_fuzzy, mock_find, *_):
    mock_find.return_value = _make_contractor(id="e1")
    match = _make_contractor(id="c1", display_name="Author X")
    mock_fuzzy.return_value = [(match, 0.8)]

    result = handle("editor_source_name", {"text": "Author X"}, {"user_id": 42})

    assert _has_keyboard(result)
    keyboards = [m["keyboard"] for m in result["messages"] if "keyboard" in m]
    flat = [btn["data"] for row in keyboards[0] for btn in row]
    assert any(d.startswith("esrc:link:") for d in flat)
    assert any(d == "esrc:stub" for d in flat)


@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id")
@patch("backend.interact.contractor.fuzzy_find", return_value=[])
def test_editor_source_name_no_match_offers_stub(mock_fuzzy, mock_find, *_):
    mock_find.return_value = _make_contractor(id="e1")

    result = handle("editor_source_name", {"text": "Unknown Author"}, {"user_id": 42})

    keyboards = [m["keyboard"] for m in result["messages"] if "keyboard" in m]
    flat = [btn["data"] for row in keyboards[0] for btn in row]
    assert any(d == "esrc:stub" for d in flat)
    assert any(d == "esrc:raw" for d in flat)


# ── Esrc callbacks ──────────────────────────────────────────────────


@patch("backend.interact.contractor.redirect_in_budget")
@patch("backend.interact.contractor.delete_invoice")
@patch("backend.interact.contractor.add_redirect_rule")
@patch("backend.interact.contractor.find_redirect_rules_by_target", return_value=[])
@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id")
def test_esrc_callback_raw_adds_source(mock_find, *_):
    mock_find.return_value = _make_contractor()

    ctx = {"user_id": 42, "fsm_data": {"pending_source_name": "Автор Тест", "editor_id": "c1"}}
    result = handle("esrc_callback", {"callback_data": "esrc:raw"}, ctx)

    assert result.get("fsm_state") is None


@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id")
def test_esrc_callback_add_prompts_name(mock_find, *_):
    mock_find.return_value = _make_contractor()

    result = handle("esrc_callback", {"callback_data": "esrc:add"}, {"user_id": 42})

    assert result.get("fsm_state") == "waiting_editor_source_name"


@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id")
def test_esrc_callback_back_shows_menu(mock_find, *_):
    mock_find.return_value = _make_contractor()

    result = handle("esrc_callback", {"callback_data": "esrc:back"}, {"user_id": 42})

    assert _has_keyboard(result)


@patch("backend.interact.contractor.unredirect_in_budget")
@patch("backend.interact.contractor.delete_invoice")
@patch("backend.interact.contractor.remove_redirect_rule", return_value=True)
@patch("backend.interact.contractor.find_redirect_rules_by_target", return_value=[])
@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id")
def test_esrc_callback_remove_source(mock_find, *_):
    mock_find.return_value = _make_contractor()

    result = handle("esrc_callback", {"callback_data": "esrc:rm:SomeName"}, {"user_id": 42})

    assert _has_keyboard(result)


@patch("backend.interact.contractor.redirect_in_budget")
@patch("backend.interact.contractor.delete_invoice")
@patch("backend.interact.contractor.add_redirect_rule")
@patch("backend.interact.contractor.find_redirect_rules_by_target", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_id")
@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id")
def test_esrc_callback_link_uses_linked_contractor(mock_find, _, mock_find_by_id, *__):
    mock_find.return_value = _make_contractor()
    linked = _make_contractor(display_name="Linked Author")
    mock_find_by_id.return_value = linked

    ctx = {"user_id": 42, "fsm_data": {"pending_source_name": "Original Name", "editor_id": "c1"}}
    result = handle("esrc_callback", {"callback_data": "esrc:link:c99"}, ctx)

    assert result.get("fsm_state") is None
    # Verify the linked name was used, not the original
    assert "Linked Author" in result["messages"][0]["text"]


@patch("backend.interact.contractor.redirect_in_budget")
@patch("backend.interact.contractor.delete_invoice")
@patch("backend.interact.contractor.add_redirect_rule")
@patch("backend.interact.contractor.find_redirect_rules_by_target", return_value=[])
@patch("backend.interact.contractor.ContractorFactory")
@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id")
def test_esrc_callback_stub_creates_and_links(mock_find, _, mock_factory_cls, *__):
    mock_find.return_value = _make_contractor()

    ctx = {"user_id": 42, "fsm_data": {"pending_source_name": "Stub Author", "editor_id": "c1"}}
    handle("esrc_callback", {"callback_data": "esrc:stub"}, ctx)

    mock_factory_cls.return_value.create_stub.assert_called_once()


# ── Dup callback ─────────────────────────────────────────────────────


def test_dup_callback_new_starts_type_selection():
    result = handle("dup_callback", {"callback_data": "dup:new"}, {"user_id": 1})

    assert result.get("fsm_state") == "waiting_type"


@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_id")
def test_dup_callback_existing_asks_code(mock_find, *_):
    mock_find.return_value = _make_contractor(telegram=None)

    result = handle("dup_callback", {"callback_data": "dup:c1"}, {"user_id": 42})

    assert result.get("fsm_state") == "waiting_verification"
    assert result["fsm_data"]["pending_contractor_id"] == "c1"


@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_id")
def test_dup_callback_already_linked_rejects(mock_find, *_):
    mock_find.return_value = _make_contractor(telegram="999")

    result = handle("dup_callback", {"callback_data": "dup:c1"}, {"user_id": 42})

    assert result.get("fsm_state") is None
    assert not _has_keyboard(result)


# ── Menu callback ────────────────────────────────────────────────────


@patch("backend.interact.contractor.InvoiceService")
@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id")
def test_menu_callback_contract(mock_find, _, mock_svc_cls):
    mock_find.return_value = _make_contractor()
    svc = mock_svc_cls.return_value
    svc.resolve_existing.return_value = None
    svc.prepare_new_data.return_value = None

    result = handle("menu_callback", {"callback_data": "menu:contract"}, {"user_id": 42})

    assert len(result["messages"]) >= 1


@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id")
def test_menu_callback_update(mock_find, *_):
    mock_find.return_value = _make_contractor()

    result = handle("menu_callback", {"callback_data": "menu:update"}, {"user_id": 42})

    assert result.get("fsm_state") == "waiting_update_data"


@patch("backend.interact.contractor.find_redirect_rules_by_target", return_value=[])
@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id")
def test_menu_callback_editor(mock_find, *_):
    mock_find.return_value = _make_contractor()

    result = handle("menu_callback", {"callback_data": "menu:editor"}, {"user_id": 42})

    assert _has_keyboard(result)


# ── Type change ──────────────────────────────────────────────────────


@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id")
def test_change_type_from_menu(mock_find, *_):
    mock_find.return_value = _make_contractor()

    result = handle("menu_callback", {"callback_data": "menu:change_type"}, {"user_id": 42})

    assert result.get("fsm_state") == "waiting_type"
    assert result["fsm_data"]["changing_type_id"] == "c1"


@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id")
def test_change_type_stub_rejected(mock_find, *_):
    mock_find.return_value = _make_contractor(is_stub=True)

    result = handle("menu_callback", {"callback_data": "menu:change_type"}, {"user_id": 42})

    assert result.get("fsm_state") is None


# ── Document handling ────────────────────────────────────────────────


@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id")
def test_document_non_global_non_samozanyaty_acknowledges(mock_find, *_):
    c = MagicMock(spec=["display_name"])
    c.display_name = "Test"
    mock_find.return_value = c

    result = handle("document", {"file_b64": "dGVzdA==", "mime": "application/pdf"}, {"user_id": 42})

    assert len(result["messages"]) == 1


@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id", return_value=None)
def test_document_unknown_user_acknowledges(*_):
    result = handle("document", {"file_b64": "dGVzdA=="}, {"user_id": 999})

    assert len(result["messages"]) == 1


# ── Non-document handling ────────────────────────────────────────────


@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id", return_value=None)
def test_non_document_no_fsm_no_contractor_returns_empty(*_):
    result = handle("non_document", {}, {"user_id": 999})

    assert result["messages"] == []


@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id")
def test_non_document_in_fsm_returns_message(mock_find, *_):
    mock_find.return_value = _make_contractor()

    result = handle("non_document", {}, {"user_id": 42, "fsm_state": "waiting_data"})

    assert len(result["messages"]) == 1


# ── Receipt upload ───────────────────────────────────────────────────


@patch("backend.interact.contractor.DriveGateway")
@patch("backend.interact.contractor.update_receipt_url")
@patch("backend.interact.contractor.load_invoices")
@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id")
def test_receipt_upload_samozanyaty_success(mock_find, _, mock_invoices, mock_update, mock_drive):
    mock_find.return_value = _make_samozanyaty()
    mock_invoices.return_value = [Invoice(
        contractor_id="c1", invoice_number=1, month="2026-02",
        amount=1000, currency=Currency.RUB, status=InvoiceStatus.SENT,
    )]
    mock_drive.return_value.upload_receipt.return_value = "https://drive.google.com/receipt"

    result = handle("document", {"file_b64": "dGVzdA==", "mime": "application/pdf"},
                    {"user_id": 42, "admin_ids": [1]})

    mock_update.assert_called_once_with("c1", "2026-02", "https://drive.google.com/receipt")
    assert len(result.get("side_messages", [])) == 1


@patch("backend.interact.contractor.load_invoices", return_value=[])
@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id")
def test_receipt_upload_no_invoice(mock_find, *_):
    mock_find.return_value = _make_samozanyaty()

    result = handle("document", {"file_b64": "dGVzdA==", "mime": "application/pdf"},
                    {"user_id": 42})

    assert len(result["messages"]) == 1


@patch("backend.interact.contractor.load_invoices")
@patch("backend.interact.contractor.load_all_contractors", return_value=[])
@patch("backend.interact.contractor.find_contractor_by_telegram_id")
def test_receipt_upload_already_uploaded(mock_find, _, mock_invoices):
    mock_find.return_value = _make_samozanyaty()
    mock_invoices.return_value = [Invoice(
        contractor_id="c1", invoice_number=1, month="2026-02",
        amount=1000, currency=Currency.RUB, status=InvoiceStatus.SENT,
        receipt_url="https://drive.google.com/existing",
    )]

    result = handle("document", {"file_b64": "dGVzdA==", "mime": "image/jpeg"},
                    {"user_id": 42})

    assert len(result["messages"]) == 1


# ── Admin: generate ──────────────────────────────────────────────────


def test_admin_generate_no_text():
    result = handle("admin_generate", {"text": ""}, {"user_id": 1})

    assert len(result["messages"]) == 1


@patch("backend.interact.admin.load_all_contractors", return_value=[])
@patch("backend.interact.admin.find_contractor", return_value=None)
@patch("backend.interact.admin.fuzzy_find", return_value=[])
def test_admin_generate_unknown_contractor(*_):
    result = handle("admin_generate", {"text": "Unknown"}, {"user_id": 1})

    assert len(result["messages"]) == 1


# ── Admin: articles ──────────────────────────────────────────────────


def test_admin_articles_no_text():
    result = handle("admin_articles", {"text": ""}, {"user_id": 1})

    assert len(result["messages"]) == 1


@patch("backend.interact.admin.RepublicGateway")
@patch("backend.interact.admin.load_all_contractors", return_value=[])
@patch("backend.interact.admin.find_contractor")
@patch("backend.interact.admin.fuzzy_find", return_value=[])
def test_admin_articles_no_publications(mock_fuzzy, mock_find, _, mock_gw):
    mock_find.return_value = _make_contractor()
    mock_gw.return_value.fetch_articles.return_value = []

    result = handle("admin_articles", {"text": "Test"}, {"user_id": 1})

    assert len(result["messages"]) == 1


@patch("backend.interact.admin.RepublicGateway")
@patch("backend.interact.admin.load_all_contractors", return_value=[])
@patch("backend.interact.admin.find_contractor")
def test_admin_articles_returns_list(mock_find, _, mock_gw):
    mock_find.return_value = _make_contractor()
    mock_gw.return_value.fetch_articles.return_value = [MagicMock(article_id="a1")]

    result = handle("admin_articles", {"text": "Test"}, {"user_id": 1})

    data = result["messages"][0]["data"]
    assert data["type"].value == "articles_list"
    assert data["count"] == 1


# ── Admin: lookup ────────────────────────────────────────────────────


def test_admin_lookup_no_text():
    result = handle("admin_lookup", {"text": ""}, {"user_id": 1})

    assert len(result["messages"]) == 1


@patch("backend.interact.admin.load_all_contractors", return_value=[])
@patch("backend.interact.admin.find_contractor")
def test_admin_lookup_returns_contractor_info(mock_find, *_):
    mock_find.return_value = _make_contractor(
        email="t@x.com", telegram="123", invoice_number=1,
        bank_name="Bank", bank_account="1234", mags="",
    )

    result = handle("admin_lookup", {"text": "Test"}, {"user_id": 1})

    data = result["messages"][0]["data"]
    assert data["type"].value == "contractor_info"
    assert data["telegram_linked"] is True


# ── Admin: orphans ───────────────────────────────────────────────────


@patch("backend.interact.admin.load_all_amounts", return_value={})
@patch("backend.interact.admin.load_all_contractors", return_value=[])
def test_admin_orphans_none_found(*_):
    result = handle("admin_orphans", {}, {"user_id": 1})

    assert len(result["messages"]) == 1


@patch("backend.interact.admin.load_all_amounts", return_value={"orphan name": (100, 0, "")})
@patch("backend.interact.admin.load_all_contractors", return_value=[])
def test_admin_orphans_returns_list(*_):
    result = handle("admin_orphans", {}, {"user_id": 1})

    data = result["messages"][0]["data"]
    assert data["type"].value == "orphan_list"
    assert "orphan name" in data["orphans"]


# ── Admin: upload statement ──────────────────────────────────────────


def test_admin_upload_statement_no_file():
    result = handle("admin_upload_statement", {"rate": "3.5"}, {"user_id": 1})

    assert len(result["messages"]) == 1


def test_admin_upload_statement_invalid_rate():
    result = handle("admin_upload_statement", {"file_b64": "dGVzdA==", "rate": "abc"}, {"user_id": 1})

    assert len(result["messages"]) == 1


# ── Admin: legium reply ──────────────────────────────────────────────


@patch("backend.interact.admin.update_legium_link")
@patch("backend.interact.admin.load_all_contractors", return_value=[])
@patch("backend.interact.admin.find_contractor_by_id", return_value=None)
def test_admin_legium_reply_no_telegram_saves_link(mock_find, _, mock_update):
    result = handle("admin_legium_reply", {
        "text": "https://legium.test/doc",
        "contractor_id": "c1",
        "contractor_telegram": "",
    }, {"user_id": 1})

    mock_update.assert_called_once()
    assert result.get("side_messages") is None or len(result["side_messages"]) == 0


@patch("backend.interact.admin.prepare_existing_invoice", return_value=None)
@patch("backend.interact.admin.update_legium_link")
@patch("backend.interact.admin.load_all_contractors", return_value=[])
@patch("backend.interact.admin.find_contractor_by_id")
def test_admin_legium_reply_with_telegram_sends(mock_find, _, mock_update, mock_prepare):
    mock_find.return_value = _make_contractor()

    result = handle("admin_legium_reply", {
        "text": "https://legium.test/doc",
        "contractor_id": "c1",
        "contractor_telegram": "123",
    }, {"user_id": 1})

    assert len(result.get("side_messages", [])) == 1


# ── Admin: batch generate ──────────────────────────────────────────


@patch("backend.interact.admin.load_all_contractors", return_value=[])
@patch("backend.interact.admin.create_generate_batch_invoices")
def test_admin_batch_generate_no_new_invoices(mock_batch_cls, *_):
    batch_result = MagicMock()
    batch_result.total = 0
    mock_batch_cls.return_value.execute.return_value = batch_result

    result = handle("admin_batch_generate", {"text": ""}, {"user_id": 1})

    assert len(result["messages"]) == 1


@patch("backend.interact.admin.load_all_contractors", return_value=[])
@patch("backend.interact.admin.create_generate_batch_invoices")
def test_admin_batch_generate_with_results(mock_batch_cls, *_):
    batch_result = MagicMock()
    batch_result.total = 2
    batch_result.counts = {"самозанятый": 1, "ИП": 1}
    batch_result.errors = []
    batch_result.generated = []
    mock_batch_cls.return_value.execute.return_value = batch_result

    result = handle("admin_batch_generate", {"text": ""}, {"user_id": 1})

    assert result["messages"][0]["data"]["type"].value == "operation_summary"


# ── Admin: send global ──────────────────────────────────────────────


@patch("backend.interact.admin.load_invoices", return_value=[])
def test_admin_send_global_no_drafts(*_):
    result = handle("admin_send_global", {"text": ""}, {"user_id": 1})

    assert len(result["messages"]) == 1


# ── Admin: send legium ──────────────────────────────────────────────


@patch("backend.interact.admin.load_invoices", return_value=[])
def test_admin_send_legium_no_pending(*_):
    result = handle("admin_send_legium", {"text": ""}, {"user_id": 1})

    assert len(result["messages"]) == 1


# ── Admin: remind receipts ───────────────────────────────────────────


@patch("backend.interact.admin.load_invoices", return_value=[])
@patch("backend.interact.admin.load_all_contractors", return_value=[])
def test_remind_receipts_none_missing(*_):
    result = handle("admin_remind_receipts", {}, {"user_id": 1})

    assert len(result["messages"]) == 1
    assert len(result.get("side_messages", [])) == 0


@patch("backend.interact.admin.load_invoices")
@patch("backend.interact.admin.load_all_contractors")
@patch("backend.interact.admin.find_contractor_by_id")
def test_remind_receipts_sends_reminders(mock_find, mock_contractors, mock_invoices):
    c = _make_samozanyaty(tid="555")
    mock_contractors.return_value = [c]
    mock_find.return_value = c
    mock_invoices.return_value = [Invoice(
        contractor_id="c1", invoice_number=1, month="2026-02",
        amount=1000, currency=Currency.RUB, status=InvoiceStatus.PAID,
    )]

    result = handle("admin_remind_receipts", {}, {"user_id": 1})

    assert len(result.get("side_messages", [])) == 1
    assert result["side_messages"][0]["chat_id"] == 555


# ── Checkpoint action ────────────────────────────────────────────────


def test_checkpoint_approve_activates_next_task(fake_db):
    goal = fake_db.create_goal(title="Pipeline")
    t_user = fake_db.create_task(title="Review", goal_id=goal["id"], assigned_to="user")
    t_next = fake_db.create_task(title="Send", goal_id=goal["id"], assigned_to="agent", depends_on=t_user["id"])
    fake_db.update_task(t_user["id"], status="in_progress")

    # Simulate approve
    from backend.interact.admin import _activate_next_task
    fake_db.update_task(t_user["id"], status="done", result="Approved")
    _activate_next_task(fake_db, fake_db.get_task(t_user["id"]))

    assert fake_db.get_task(t_next["id"])["status"] == "in_progress"
