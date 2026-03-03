import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from common.models import (
    ContractorType,
    Currency,
    GlobalContractor,
    Invoice,
    InvoiceStatus,
    IPContractor,
    RoleCode,
    SamozanyatyContractor,
)
from telegram_bot import replies


# ---------------------------------------------------------------------------
#  Factories
# ---------------------------------------------------------------------------

def _global(**overrides) -> GlobalContractor:
    kwargs = dict(
        id="g1", name_en="Test Global", address="Addr", email="a@b.c",
        bank_name="Bank", bank_account="ACC", swift="SWIFT",
    )
    kwargs.update(overrides)
    return GlobalContractor(**kwargs)


def _samoz(**overrides) -> SamozanyatyContractor:
    kwargs = dict(
        id="s1", name_ru="Тест Самозанятый", address="Адрес", email="s@t.ru",
        bank_name="Банк", bank_account="12345", bik="044525225",
        corr_account="30101810400000000225",
        passport_series="1234", passport_number="567890", inn="123456789012",
    )
    kwargs.update(overrides)
    return SamozanyatyContractor(**kwargs)


def _ip(**overrides) -> IPContractor:
    kwargs = dict(
        id="ip1", name_ru="Тест ИП", email="ip@test.ru",
        bank_name="Банк", bank_account="12345", bik="044525225",
        corr_account="30101810400000000225",
        ogrnip="123456789012345",
    )
    kwargs.update(overrides)
    return IPContractor(**kwargs)


def _make_message(text: str = "", chat_id: int = 100, user_id: int = 42) -> AsyncMock:
    msg = AsyncMock()
    msg.text = text
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    msg.chat.type = "private"
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.message_id = 10
    msg.reply_to_message = None
    msg.answer = AsyncMock()
    msg.reply = AsyncMock()
    msg.answer_document = AsyncMock()
    msg.document = None
    return msg


def _make_state(data=None) -> AsyncMock:
    state = AsyncMock()
    state.get_state.return_value = None
    _data = data or {}
    state.get_data.return_value = _data
    state.update_data = AsyncMock()
    state.set_data = AsyncMock()
    state.set_state = AsyncMock()
    state.clear = AsyncMock()
    return state


def _callback(data: str, user_id: int = 42) -> AsyncMock:
    cb = AsyncMock()
    cb.data = data
    cb.from_user = MagicMock()
    cb.from_user.id = user_id
    cb.answer = AsyncMock()
    cb.message = AsyncMock()
    cb.message.chat.id = 100
    cb.message.message_id = 10
    cb.message.answer = AsyncMock()
    cb.message.edit_text = AsyncMock()
    cb.message.delete = AsyncMock()
    return cb


def _invoice(**overrides) -> Invoice:
    kwargs = dict(
        contractor_id="s1", contractor_name="Тест",
        invoice_number=1, month="2026-02",
        amount=Decimal("5000"), currency=Currency.RUB,
        status=InvoiceStatus.DRAFT,
    )
    kwargs.update(overrides)
    return Invoice(**kwargs)


# ===================================================================
#  _linked_menu_markup
# ===================================================================

class TestLinkedMenuMarkup:

    def test_author_has_contract_and_update(self):
        from telegram_bot.handlers.contractor_handlers import _linked_menu_markup

        contractor = _samoz(role_code=RoleCode.AUTHOR)
        markup = _linked_menu_markup(contractor)

        callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert "menu:contract" in callbacks
        assert "menu:update" in callbacks
        assert "menu:editor" not in callbacks

    def test_redaktor_has_editor_sources_btn(self):
        from telegram_bot.handlers.contractor_handlers import _linked_menu_markup

        contractor = _samoz(role_code=RoleCode.REDAKTOR)
        markup = _linked_menu_markup(contractor)

        callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert "menu:editor" in callbacks


# ===================================================================
#  handle_start
# ===================================================================

class TestHandleStart:

    @patch("telegram_bot.handlers.contractor_handlers.is_admin", return_value=True)
    def test_admin_gets_admin_message(self, mock_admin):
        from telegram_bot.handlers.contractor_handlers import handle_start

        msg = _make_message("/start")
        state = _make_state()

        asyncio.run(handle_start(msg, state))

        state.clear.assert_awaited_once()
        text = msg.answer.call_args[0][0]
        assert text == replies.start.admin

    @patch("telegram_bot.handlers.contractor_handlers.is_admin", return_value=False)
    def test_contractor_gets_welcome(self, mock_admin):
        from telegram_bot.handlers.contractor_handlers import handle_start

        msg = _make_message("/start")
        state = _make_state()

        asyncio.run(handle_start(msg, state))

        text = msg.answer.call_args[0][0]
        assert text == replies.start.contractor


# ===================================================================
#  handle_menu
# ===================================================================

class TestHandleMenu:

    @patch("telegram_bot.handlers.contractor_handlers.is_admin", return_value=True)
    def test_admin_gets_admin_menu(self, mock_admin):
        from telegram_bot.handlers.contractor_handlers import handle_menu

        msg = _make_message("/menu")
        state = _make_state()

        asyncio.run(handle_menu(msg, state))

        text = msg.answer.call_args[0][0]
        assert text == replies.menu.admin

    @patch("telegram_bot.handlers.contractor_handlers.get_current_contractor", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.contractor_handlers.is_admin", return_value=False)
    def test_linked_contractor_gets_menu_buttons(self, mock_admin, mock_get):
        from telegram_bot.handlers.contractor_handlers import handle_menu

        mock_get.return_value = _samoz()

        msg = _make_message("/menu")
        state = _make_state()

        asyncio.run(handle_menu(msg, state))

        text = msg.answer.call_args[0][0]
        assert text == replies.menu.prompt
        assert msg.answer.call_args[1]["reply_markup"] is not None

    @patch("telegram_bot.handlers.contractor_handlers.get_current_contractor", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.contractor_handlers.is_admin", return_value=False)
    def test_unknown_user_gets_start(self, mock_admin, mock_get):
        from telegram_bot.handlers.contractor_handlers import handle_menu

        mock_get.return_value = None

        msg = _make_message("/menu")
        state = _make_state()

        asyncio.run(handle_menu(msg, state))

        text = msg.answer.call_args[0][0]
        assert text == replies.start.contractor


# ===================================================================
#  handle_type_selection
# ===================================================================

class TestHandleTypeSelection:

    def test_valid_type_1_samoz(self):
        from telegram_bot.handlers.contractor_handlers import handle_type_selection

        msg = _make_message("1")
        state = _make_state(data={"alias": "Вася"})

        result = asyncio.run(handle_type_selection(msg, state))

        assert result == "valid"
        set_data_call = state.set_data.call_args[0][0]
        assert set_data_call["contractor_type"] == ContractorType.SAMOZANYATY.value

    def test_valid_type_3_global(self):
        from telegram_bot.handlers.contractor_handlers import handle_type_selection

        msg = _make_message("3")
        state = _make_state(data={"alias": ""})

        result = asyncio.run(handle_type_selection(msg, state))

        assert result == "valid"
        set_data_call = state.set_data.call_args[0][0]
        assert set_data_call["contractor_type"] == ContractorType.GLOBAL.value

    def test_invalid_type(self):
        from telegram_bot.handlers.contractor_handlers import handle_type_selection

        msg = _make_message("4")
        state = _make_state(data={})

        result = asyncio.run(handle_type_selection(msg, state))

        assert result is None
        msg.answer.assert_awaited_once()
        assert msg.answer.call_args[0][0] == replies.registration.type_invalid

    def test_text_samozanyaty(self):
        from telegram_bot.handlers.contractor_handlers import handle_type_selection

        msg = _make_message("Самозанятый")
        state = _make_state(data={"alias": "Иван"})

        result = asyncio.run(handle_type_selection(msg, state))

        assert result == "valid"

    def test_text_global(self):
        from telegram_bot.handlers.contractor_handlers import handle_type_selection

        msg = _make_message("global")
        state = _make_state(data={})

        result = asyncio.run(handle_type_selection(msg, state))

        assert result == "valid"

    def test_alias_preserved_in_collected(self):
        from telegram_bot.handlers.contractor_handlers import handle_type_selection

        msg = _make_message("1")
        state = _make_state(data={"alias": "Вася Пупкин"})

        asyncio.run(handle_type_selection(msg, state))

        set_data_call = state.set_data.call_args[0][0]
        assert set_data_call["collected_data"]["aliases"] == ["Вася Пупкин"]


# ===================================================================
#  handle_contractor_text
# ===================================================================

class TestHandleContractorText:

    @patch("telegram_bot.handlers.contractor_handlers.find_contractor_by_telegram_id")
    @patch("telegram_bot.handlers.contractor_handlers.is_admin", return_value=True)
    @patch("telegram_bot.handlers.contractor_handlers.get_contractors", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.contractor_handlers.send_typing", new_callable=AsyncMock)
    def test_admin_gets_menu(self, mock_typing, mock_get, mock_admin, mock_find):
        from telegram_bot.handlers.contractor_handlers import handle_contractor_text

        mock_get.return_value = []

        msg = _make_message("hello")
        state = _make_state()

        result = asyncio.run(handle_contractor_text(msg, state))

        assert result is None
        msg.answer.assert_awaited_once()
        assert msg.answer.call_args[0][0] == replies.menu.admin

    @patch("telegram_bot.handlers.contractor_handlers.find_contractor_by_telegram_id")
    @patch("telegram_bot.handlers.contractor_handlers.is_admin", return_value=False)
    @patch("telegram_bot.handlers.contractor_handlers.get_contractors", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.contractor_handlers.send_typing", new_callable=AsyncMock)
    def test_linked_user_gets_menu(self, mock_typing, mock_get, mock_admin, mock_find):
        from telegram_bot.handlers.contractor_handlers import handle_contractor_text

        contractor = _samoz(telegram="42")
        mock_get.return_value = [contractor]
        mock_find.return_value = contractor

        msg = _make_message("hello")
        state = _make_state()

        result = asyncio.run(handle_contractor_text(msg, state))

        assert result is None
        text = msg.answer.call_args[0][0]
        assert text == replies.menu.prompt

    @patch("telegram_bot.handlers.contractor_handlers.fuzzy_find")
    @patch("telegram_bot.handlers.contractor_handlers.find_contractor_by_telegram_id")
    @patch("telegram_bot.handlers.contractor_handlers.is_admin", return_value=False)
    @patch("telegram_bot.handlers.contractor_handlers.get_contractors", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.contractor_handlers.send_typing", new_callable=AsyncMock)
    def test_fuzzy_match_shows_buttons(self, mock_typing, mock_get, mock_admin, mock_find, mock_fuzzy):
        from telegram_bot.handlers.contractor_handlers import handle_contractor_text

        contractor = _samoz()
        mock_get.return_value = [contractor]
        mock_find.return_value = None
        mock_fuzzy.return_value = [(contractor, 0.9)]

        msg = _make_message("Тест")
        state = _make_state()

        result = asyncio.run(handle_contractor_text(msg, state))

        assert result is None
        msg.answer.assert_awaited()
        # Should show inline keyboard with contractor + "new" button
        markup = msg.answer.call_args[1]["reply_markup"]
        assert markup is not None

    @patch("telegram_bot.handlers.contractor_handlers.fuzzy_find")
    @patch("telegram_bot.handlers.contractor_handlers.find_contractor_by_telegram_id")
    @patch("telegram_bot.handlers.contractor_handlers.is_admin", return_value=False)
    @patch("telegram_bot.handlers.contractor_handlers.get_contractors", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.contractor_handlers.send_typing", new_callable=AsyncMock)
    def test_no_match_returns_register(self, mock_typing, mock_get, mock_admin, mock_find, mock_fuzzy):
        from telegram_bot.handlers.contractor_handlers import handle_contractor_text

        mock_get.return_value = []
        mock_find.return_value = None
        mock_fuzzy.return_value = []

        msg = _make_message("Новый контрагент")
        state = _make_state()

        result = asyncio.run(handle_contractor_text(msg, state))

        assert result == "register"


# ===================================================================
#  handle_non_document
# ===================================================================

class TestHandleNonDocument:

    @patch("telegram_bot.handlers.contractor_handlers.get_current_contractor", new_callable=AsyncMock)
    def test_in_fsm_state_reminds_text(self, mock_get):
        from telegram_bot.handlers.contractor_handlers import handle_non_document

        msg = _make_message("")
        state = _make_state()
        state.get_state.return_value = "ContractorStates:waiting_data"

        asyncio.run(handle_non_document(msg, state))

        msg.answer.assert_awaited_once()
        assert msg.answer.call_args[0][0] == replies.generic.text_expected

    @patch("telegram_bot.handlers.contractor_handlers.get_current_contractor", new_callable=AsyncMock)
    def test_global_contractor_gets_pdf_reminder(self, mock_get):
        from telegram_bot.handlers.contractor_handlers import handle_non_document

        mock_get.return_value = _global()

        msg = _make_message("")
        state = _make_state()

        asyncio.run(handle_non_document(msg, state))

        msg.answer.assert_awaited_once()
        assert msg.answer.call_args[0][0] == replies.document.pdf_reminder

    @patch("telegram_bot.handlers.contractor_handlers.get_current_contractor", new_callable=AsyncMock)
    def test_non_global_contractor_no_reminder(self, mock_get):
        from telegram_bot.handlers.contractor_handlers import handle_non_document

        mock_get.return_value = _samoz()

        msg = _make_message("")
        state = _make_state()

        asyncio.run(handle_non_document(msg, state))

        msg.answer.assert_not_awaited()


# ===================================================================
#  handle_document
# ===================================================================

class TestHandleDocument:

    @patch("telegram_bot.handlers.contractor_handlers.is_admin", return_value=True)
    def test_admin_documents_ignored(self, mock_admin):
        from telegram_bot.handlers.contractor_handlers import handle_document

        msg = _make_message("")
        state = _make_state()

        asyncio.run(handle_document(msg, state))

        msg.answer.assert_not_awaited()

    @patch("telegram_bot.handlers.contractor_handlers.ADMIN_TELEGRAM_IDS", [999])
    @patch("telegram_bot.handlers.contractor_handlers.bot", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.contractor_handlers.get_current_contractor", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.contractor_handlers.is_admin", return_value=False)
    def test_non_global_forwards_to_admins(self, mock_admin, mock_get, mock_bot):
        from telegram_bot.handlers.contractor_handlers import handle_document

        mock_get.return_value = _samoz()

        msg = _make_message("", user_id=42)
        msg.document = MagicMock()
        state = _make_state()

        asyncio.run(handle_document(msg, state))

        msg.answer.assert_awaited()
        assert msg.answer.call_args[0][0] == replies.document.received
        mock_bot.forward_message.assert_awaited()

    @patch("telegram_bot.handlers.contractor_handlers.ADMIN_TELEGRAM_IDS", [999])
    @patch("telegram_bot.handlers.contractor_handlers.update_invoice_status")
    @patch("telegram_bot.handlers.contractor_handlers.upload_invoice_pdf")
    @patch("telegram_bot.handlers.contractor_handlers.bot", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.contractor_handlers.get_current_contractor", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.contractor_handlers.is_admin", return_value=False)
    def test_global_pdf_uploaded_to_drive(self, mock_admin, mock_get, mock_bot, mock_upload, mock_update):
        from telegram_bot.handlers.contractor_handlers import handle_document

        mock_get.return_value = _global(telegram="42")
        mock_upload.return_value = "https://drive.google.com/file/123"

        file_mock = MagicMock()
        file_mock.file_path = "/tmp/test.pdf"
        mock_bot.get_file.return_value = file_mock
        file_bytes_mock = MagicMock()
        file_bytes_mock.read.return_value = b"pdf-data"
        mock_bot.download_file.return_value = file_bytes_mock

        msg = _make_message("", user_id=42)
        msg.document = MagicMock()
        msg.document.mime_type = "application/pdf"
        msg.document.file_id = "file-123"
        msg.document.file_name = "signed.pdf"
        state = _make_state()

        asyncio.run(handle_document(msg, state))

        mock_upload.assert_called_once()
        mock_update.assert_called_once()

    @patch("telegram_bot.handlers.contractor_handlers.ADMIN_TELEGRAM_IDS", [999])
    @patch("telegram_bot.handlers.contractor_handlers.bot", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.contractor_handlers.get_current_contractor", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.contractor_handlers.is_admin", return_value=False)
    def test_global_non_pdf_rejected(self, mock_admin, mock_get, mock_bot):
        from telegram_bot.handlers.contractor_handlers import handle_document

        mock_get.return_value = _global(telegram="42")

        msg = _make_message("", user_id=42)
        msg.document = MagicMock()
        msg.document.mime_type = "image/png"
        state = _make_state()

        asyncio.run(handle_document(msg, state))

        msg.answer.assert_awaited()
        assert msg.answer.call_args[0][0] == replies.document.pdf_required


# ===================================================================
#  handle_duplicate_callback
# ===================================================================

class TestHandleDuplicateCallback:

    @patch("telegram_bot.handlers.contractor_handlers._safe_edit_text", new_callable=AsyncMock)
    def test_new_contractor_starts_registration(self, mock_edit):
        from telegram_bot.handlers.contractor_handlers import handle_duplicate_callback

        cb = _callback("dup:new")
        state = _make_state()

        asyncio.run(handle_duplicate_callback(cb, state))

        state.set_state.assert_awaited_once_with("ContractorStates:waiting_type")
        cb.message.answer.assert_awaited()
        assert replies.registration.type_prompt in cb.message.answer.call_args[0][0]

    @patch("telegram_bot.handlers.contractor_handlers.send_typing", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.contractor_handlers._safe_edit_text", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.contractor_handlers.get_contractor_by_id", new_callable=AsyncMock)
    def test_select_contractor_enters_verification(self, mock_get, mock_edit, mock_typing):
        from telegram_bot.handlers.contractor_handlers import handle_duplicate_callback

        contractor = _samoz(secret_code="SECRET123", telegram="")
        mock_get.return_value = contractor

        cb = _callback("dup:s1", user_id=42)
        state = _make_state()

        asyncio.run(handle_duplicate_callback(cb, state))

        state.set_state.assert_awaited_once_with("ContractorStates:waiting_verification")
        cb.message.answer.assert_awaited()

    @patch("telegram_bot.handlers.contractor_handlers.send_typing", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.contractor_handlers._safe_edit_text", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.contractor_handlers.get_contractor_by_id", new_callable=AsyncMock)
    def test_already_bound_to_other_shows_error(self, mock_get, mock_edit, mock_typing):
        from telegram_bot.handlers.contractor_handlers import handle_duplicate_callback

        contractor = _samoz(telegram="999")  # Bound to different user
        mock_get.return_value = contractor

        cb = _callback("dup:s1", user_id=42)
        state = _make_state()

        asyncio.run(handle_duplicate_callback(cb, state))

        text = cb.message.answer.call_args[0][0]
        assert "уже привязан" in text.lower()

    @patch("telegram_bot.handlers.contractor_handlers._safe_edit_text", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.contractor_handlers.get_contractor_by_id", new_callable=AsyncMock)
    def test_contractor_not_found(self, mock_get, mock_edit):
        from telegram_bot.handlers.contractor_handlers import handle_duplicate_callback

        mock_get.return_value = None

        cb = _callback("dup:unknown")
        state = _make_state()

        asyncio.run(handle_duplicate_callback(cb, state))

        cb.message.answer.assert_awaited()
        assert cb.message.answer.call_args[0][0] == replies.lookup.not_found


# ===================================================================
#  handle_linked_menu_callback
# ===================================================================

class TestHandleLinkedMenuCallback:

    @patch("telegram_bot.handlers.contractor_handlers.get_current_contractor", new_callable=AsyncMock)
    def test_no_contractor_shows_not_found(self, mock_get):
        from telegram_bot.handlers.contractor_handlers import handle_linked_menu_callback

        mock_get.return_value = None

        cb = _callback("menu:contract")
        state = _make_state()

        asyncio.run(handle_linked_menu_callback(cb, state))

        cb.message.answer.assert_awaited()
        assert cb.message.answer.call_args[0][0] == replies.lookup.not_found

    @patch("telegram_bot.handlers.contractor_handlers._deliver_or_start_invoice", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.contractor_handlers.get_current_contractor", new_callable=AsyncMock)
    def test_contract_action_delivers_invoice(self, mock_get, mock_deliver):
        from telegram_bot.handlers.contractor_handlers import handle_linked_menu_callback

        mock_get.return_value = _samoz()

        cb = _callback("menu:contract")
        state = _make_state()

        asyncio.run(handle_linked_menu_callback(cb, state))

        mock_deliver.assert_awaited_once()

    @patch("telegram_bot.handlers.contractor_handlers.get_current_contractor", new_callable=AsyncMock)
    def test_update_action_sets_state(self, mock_get):
        from telegram_bot.handlers.contractor_handlers import handle_linked_menu_callback

        mock_get.return_value = _samoz()

        cb = _callback("menu:update")
        state = _make_state()

        asyncio.run(handle_linked_menu_callback(cb, state))

        state.set_state.assert_awaited_once_with("ContractorStates:waiting_update_data")


# ===================================================================
#  handle_verification_code
# ===================================================================

class TestHandleVerificationCode:

    @patch("telegram_bot.handlers.contractor_handlers.ADMIN_TELEGRAM_IDS", [999])
    @patch("telegram_bot.handlers.contractor_handlers.bot", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.contractor_handlers.bind_telegram_id")
    @patch("telegram_bot.handlers.contractor_handlers.get_contractor_by_id", new_callable=AsyncMock)
    def test_correct_code_binds(self, mock_get, mock_bind, mock_bot):
        from telegram_bot.handlers.contractor_handlers import handle_verification_code

        contractor = _samoz(secret_code="ABC123")
        mock_get.return_value = contractor

        msg = _make_message("ABC123", user_id=42)
        state = _make_state(data={"pending_contractor_id": "s1", "verification_attempts": 0})

        result = asyncio.run(handle_verification_code(msg, state))

        assert result == "verified"
        mock_bind.assert_called_once_with("s1", 42)
        state.clear.assert_awaited_once()

    @patch("telegram_bot.handlers.contractor_handlers.ADMIN_TELEGRAM_IDS", [999])
    @patch("telegram_bot.handlers.contractor_handlers.bot", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.contractor_handlers.bind_telegram_id")
    @patch("telegram_bot.handlers.contractor_handlers.get_contractor_by_id", new_callable=AsyncMock)
    def test_case_insensitive_code(self, mock_get, mock_bind, mock_bot):
        from telegram_bot.handlers.contractor_handlers import handle_verification_code

        contractor = _samoz(secret_code="ABC123")
        mock_get.return_value = contractor

        msg = _make_message("abc123", user_id=42)
        state = _make_state(data={"pending_contractor_id": "s1", "verification_attempts": 0})

        result = asyncio.run(handle_verification_code(msg, state))

        assert result == "verified"

    @patch("telegram_bot.handlers.contractor_handlers.get_contractor_by_id", new_callable=AsyncMock)
    def test_wrong_code_increments_attempts(self, mock_get):
        from telegram_bot.handlers.contractor_handlers import handle_verification_code

        contractor = _samoz(secret_code="ABC123")
        mock_get.return_value = contractor

        msg = _make_message("WRONG")
        state = _make_state(data={"pending_contractor_id": "s1", "verification_attempts": 0})

        result = asyncio.run(handle_verification_code(msg, state))

        assert result is None
        state.update_data.assert_awaited_once()
        text = msg.answer.call_args[0][0]
        assert "2" in text  # 2 attempts remaining

    @patch("telegram_bot.handlers.contractor_handlers.get_contractor_by_id", new_callable=AsyncMock)
    def test_too_many_attempts_locks_out(self, mock_get):
        from telegram_bot.handlers.contractor_handlers import handle_verification_code

        contractor = _samoz(secret_code="ABC123")
        mock_get.return_value = contractor

        msg = _make_message("WRONG")
        state = _make_state(data={"pending_contractor_id": "s1", "verification_attempts": 2})

        result = asyncio.run(handle_verification_code(msg, state))

        assert result is None
        state.clear.assert_awaited_once()
        text = msg.answer.call_args[0][0]
        assert "превышено" in text.lower()

    @patch("telegram_bot.handlers.contractor_handlers.get_contractor_by_id", new_callable=AsyncMock)
    def test_contractor_not_found(self, mock_get):
        from telegram_bot.handlers.contractor_handlers import handle_verification_code

        mock_get.return_value = None

        msg = _make_message("CODE")
        state = _make_state(data={"pending_contractor_id": "bad-id"})

        result = asyncio.run(handle_verification_code(msg, state))

        assert result is None
        state.clear.assert_awaited_once()


# ===================================================================
#  handle_amount_input
# ===================================================================

class TestHandleAmountInput:

    @patch("telegram_bot.handlers.contractor_handlers.update_invoice_status")
    @patch("telegram_bot.handlers.contractor_handlers.create_and_save_invoice")
    @patch("telegram_bot.handlers.contractor_handlers.fetch_articles")
    @patch("telegram_bot.handlers.contractor_handlers.bot", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.contractor_handlers.get_contractor_by_id", new_callable=AsyncMock)
    def test_ok_uses_default_amount(self, mock_get, mock_bot, mock_fetch, mock_create, mock_update):
        from telegram_bot.handlers.contractor_handlers import handle_amount_input

        contractor = _global(telegram="42")
        mock_get.return_value = contractor
        mock_fetch.return_value = []

        inv = _invoice(contractor_id="g1", currency=Currency.EUR)
        mock_create.return_value = MagicMock(pdf_bytes=b"pdf", invoice=inv)

        msg = _make_message("ок")
        state = _make_state(data={
            "invoice_contractor_id": "g1",
            "invoice_month": "2026-02",
            "invoice_default_amount": 1000,
        })

        result = asyncio.run(handle_amount_input(msg, state))

        assert result == "done"
        create_call = mock_create.call_args
        assert create_call[0][2] == Decimal("1000")

    @patch("telegram_bot.handlers.contractor_handlers._notify_admins_rub_invoice", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.contractor_handlers.create_and_save_invoice")
    @patch("telegram_bot.handlers.contractor_handlers.fetch_articles")
    @patch("telegram_bot.handlers.contractor_handlers.bot", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.contractor_handlers.get_contractor_by_id", new_callable=AsyncMock)
    def test_custom_amount(self, mock_get, mock_bot, mock_fetch, mock_create, mock_notify):
        from telegram_bot.handlers.contractor_handlers import handle_amount_input

        contractor = _samoz(telegram="42")
        mock_get.return_value = contractor
        mock_fetch.return_value = []

        inv = _invoice(currency=Currency.RUB)
        mock_create.return_value = MagicMock(pdf_bytes=b"pdf", invoice=inv)

        msg = _make_message("7500")
        state = _make_state(data={
            "invoice_contractor_id": "s1",
            "invoice_month": "2026-02",
            "invoice_default_amount": 5000,
        })

        result = asyncio.run(handle_amount_input(msg, state))

        assert result == "done"
        create_call = mock_create.call_args
        assert create_call[0][2] == Decimal("7500")

    @patch("telegram_bot.handlers.contractor_handlers.get_contractor_by_id", new_callable=AsyncMock)
    def test_invalid_amount(self, mock_get):
        from telegram_bot.handlers.contractor_handlers import handle_amount_input

        mock_get.return_value = _samoz()

        msg = _make_message("abc")
        state = _make_state(data={
            "invoice_contractor_id": "s1",
            "invoice_month": "2026-02",
            "invoice_default_amount": 5000,
        })

        result = asyncio.run(handle_amount_input(msg, state))

        assert result is None
        text = msg.answer.call_args[0][0]
        assert text == replies.invoice.amount_invalid

    @patch("telegram_bot.handlers.contractor_handlers.get_contractor_by_id", new_callable=AsyncMock)
    def test_contractor_not_found(self, mock_get):
        from telegram_bot.handlers.contractor_handlers import handle_amount_input

        mock_get.return_value = None

        msg = _make_message("ок")
        state = _make_state(data={
            "invoice_contractor_id": "bad",
            "invoice_month": "2026-02",
        })

        result = asyncio.run(handle_amount_input(msg, state))

        assert result == "done"
        assert msg.answer.call_args[0][0] == replies.lookup.not_found

    @patch("telegram_bot.handlers.contractor_handlers.create_and_save_invoice")
    @patch("telegram_bot.handlers.contractor_handlers.fetch_articles")
    @patch("telegram_bot.handlers.contractor_handlers.bot", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.contractor_handlers.get_contractor_by_id", new_callable=AsyncMock)
    def test_generation_error(self, mock_get, mock_bot, mock_fetch, mock_create):
        from telegram_bot.handlers.contractor_handlers import handle_amount_input

        mock_get.return_value = _samoz()
        mock_fetch.return_value = []
        mock_create.side_effect = Exception("PDF error")

        msg = _make_message("ок")
        state = _make_state(data={
            "invoice_contractor_id": "s1",
            "invoice_month": "2026-02",
            "invoice_default_amount": 5000,
        })

        result = asyncio.run(handle_amount_input(msg, state))

        assert result == "done"
        last_call = msg.answer.call_args[0][0]
        assert "PDF error" in last_call


# ===================================================================
#  handle_update_data
# ===================================================================

class TestHandleUpdateData:

    @patch("telegram_bot.handlers.contractor_handlers.get_current_contractor", new_callable=AsyncMock)
    def test_cancel(self, mock_get):
        from telegram_bot.handlers.contractor_handlers import handle_update_data

        msg = _make_message("отмена")
        state = _make_state()

        result = asyncio.run(handle_update_data(msg, state))

        assert result == "done"
        state.clear.assert_awaited_once()
        assert msg.answer.call_args[0][0] == replies.linked_menu.update_cancelled

    @patch("telegram_bot.handlers.contractor_handlers.get_current_contractor", new_callable=AsyncMock)
    def test_no_contractor(self, mock_get):
        from telegram_bot.handlers.contractor_handlers import handle_update_data

        mock_get.return_value = None

        msg = _make_message("новый email: test@test.com")
        state = _make_state()

        result = asyncio.run(handle_update_data(msg, state))

        assert result == "done"
        assert msg.answer.call_args[0][0] == replies.lookup.not_found

    @patch("telegram_bot.handlers.contractor_handlers.update_contractor_fields")
    @patch("telegram_bot.handlers.contractor_handlers._parse_with_llm", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.contractor_handlers.get_current_contractor", new_callable=AsyncMock)
    def test_successful_update(self, mock_get, mock_parse, mock_update):
        from telegram_bot.handlers.contractor_handlers import handle_update_data

        mock_get.return_value = _samoz()
        mock_parse.return_value = {"email": "new@test.com"}

        msg = _make_message("email: new@test.com")
        state = _make_state()

        result = asyncio.run(handle_update_data(msg, state))

        assert result == "done"
        mock_update.assert_called_once()
        assert msg.answer.call_args[0][0] == replies.linked_menu.update_success

    @patch("telegram_bot.handlers.contractor_handlers._parse_with_llm", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.contractor_handlers.get_current_contractor", new_callable=AsyncMock)
    def test_parse_error(self, mock_get, mock_parse):
        from telegram_bot.handlers.contractor_handlers import handle_update_data

        mock_get.return_value = _samoz()
        mock_parse.return_value = {"parse_error": True}

        msg = _make_message("gibberish")
        state = _make_state()

        result = asyncio.run(handle_update_data(msg, state))

        assert result is None
        assert msg.answer.call_args[0][0] == replies.registration.parse_error

    @patch("telegram_bot.handlers.contractor_handlers._parse_with_llm", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.contractor_handlers.get_current_contractor", new_callable=AsyncMock)
    def test_no_changes_detected(self, mock_get, mock_parse):
        from telegram_bot.handlers.contractor_handlers import handle_update_data

        mock_get.return_value = _samoz()
        mock_parse.return_value = {"comment": "not sure what to change"}

        msg = _make_message("something vague")
        state = _make_state()

        result = asyncio.run(handle_update_data(msg, state))

        assert result is None
        assert msg.answer.call_args[0][0] == replies.linked_menu.no_changes


# ===================================================================
#  _editor_sources_content
# ===================================================================

class TestEditorSourcesContent:

    def test_with_rules(self):
        from telegram_bot.handlers.contractor_handlers import _editor_sources_content

        rules = [
            MagicMock(source_name="Автор А"),
            MagicMock(source_name="Автор Б"),
        ]
        text, markup = _editor_sources_content(rules)

        assert "Автор А" in text
        assert "Автор Б" in text
        # Should have remove buttons + add + back
        callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert "esrc:rm:Автор А" in callbacks
        assert "esrc:rm:Автор Б" in callbacks
        assert "esrc:add" in callbacks
        assert "esrc:back" in callbacks

    def test_empty_rules(self):
        from telegram_bot.handlers.contractor_handlers import _editor_sources_content

        text, markup = _editor_sources_content([])

        assert text == replies.editor_sources.empty
        callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert "esrc:add" in callbacks
        assert "esrc:back" in callbacks


# ===================================================================
#  handle_editor_source_callback
# ===================================================================

class TestHandleEditorSourceCallback:

    @patch("telegram_bot.handlers.contractor_handlers.get_current_contractor", new_callable=AsyncMock)
    def test_no_contractor(self, mock_get):
        from telegram_bot.handlers.contractor_handlers import handle_editor_source_callback

        mock_get.return_value = None

        cb = _callback("esrc:add")
        state = _make_state()

        asyncio.run(handle_editor_source_callback(cb, state))

        cb.message.answer.assert_awaited()
        assert cb.message.answer.call_args[0][0] == replies.lookup.not_found

    @patch("telegram_bot.handlers.contractor_handlers._safe_edit_text", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.contractor_handlers._show_editor_sources", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.contractor_handlers.unredirect_in_budget")
    @patch("telegram_bot.handlers.contractor_handlers.delete_invoice")
    @patch("telegram_bot.handlers.contractor_handlers.remove_redirect_rule")
    @patch("telegram_bot.handlers.contractor_handlers.get_current_contractor", new_callable=AsyncMock)
    def test_remove_source(self, mock_get, mock_remove, mock_delete, mock_unredir, mock_show, mock_edit):
        from telegram_bot.handlers.contractor_handlers import handle_editor_source_callback

        contractor = _samoz(role_code=RoleCode.REDAKTOR)
        mock_get.return_value = contractor
        mock_remove.return_value = True

        cb = _callback("esrc:rm:Автор А")
        state = _make_state()

        asyncio.run(handle_editor_source_callback(cb, state))

        mock_remove.assert_called_once_with("Автор А", contractor.id)
        mock_delete.assert_called_once()
        mock_unredir.assert_called_once()
        mock_show.assert_awaited_once()

    @patch("telegram_bot.handlers.contractor_handlers.get_current_contractor", new_callable=AsyncMock)
    def test_add_sets_state(self, mock_get):
        from telegram_bot.handlers.contractor_handlers import handle_editor_source_callback

        contractor = _samoz(role_code=RoleCode.REDAKTOR)
        mock_get.return_value = contractor

        cb = _callback("esrc:add")
        state = _make_state()

        asyncio.run(handle_editor_source_callback(cb, state))

        state.set_state.assert_awaited_once_with("ContractorStates:waiting_editor_source_name")

    @patch("telegram_bot.handlers.contractor_handlers._safe_edit_text", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.contractor_handlers.get_current_contractor", new_callable=AsyncMock)
    def test_back_returns_to_menu(self, mock_get, mock_edit):
        from telegram_bot.handlers.contractor_handlers import handle_editor_source_callback

        contractor = _samoz(role_code=RoleCode.REDAKTOR)
        mock_get.return_value = contractor

        cb = _callback("esrc:back")
        state = _make_state()

        asyncio.run(handle_editor_source_callback(cb, state))

        mock_edit.assert_awaited_once()
        assert replies.menu.prompt in mock_edit.call_args[0][1]


# ===================================================================
#  handle_editor_source_name
# ===================================================================

class TestHandleEditorSourceName:

    @patch("telegram_bot.handlers.contractor_handlers.get_current_contractor", new_callable=AsyncMock)
    def test_cancel(self, mock_get):
        from telegram_bot.handlers.contractor_handlers import handle_editor_source_name

        msg = _make_message("отмена")
        state = _make_state()

        result = asyncio.run(handle_editor_source_name(msg, state))

        assert result == "done"
        state.clear.assert_awaited_once()

    @patch("telegram_bot.handlers.contractor_handlers.find_redirect_rules_by_target")
    @patch("telegram_bot.handlers.contractor_handlers.redirect_in_budget")
    @patch("telegram_bot.handlers.contractor_handlers.delete_invoice")
    @patch("telegram_bot.handlers.contractor_handlers.add_redirect_rule")
    @patch("telegram_bot.handlers.contractor_handlers.get_current_contractor", new_callable=AsyncMock)
    def test_adds_source(self, mock_get, mock_add, mock_delete, mock_redirect, mock_rules):
        from telegram_bot.handlers.contractor_handlers import handle_editor_source_name

        contractor = _samoz(role_code=RoleCode.REDAKTOR)
        mock_get.return_value = contractor
        mock_rules.return_value = []

        msg = _make_message("Новый автор")
        state = _make_state()

        result = asyncio.run(handle_editor_source_name(msg, state))

        assert result == "done"
        mock_add.assert_called_once()

    @patch("telegram_bot.handlers.contractor_handlers.get_current_contractor", new_callable=AsyncMock)
    def test_no_contractor(self, mock_get):
        from telegram_bot.handlers.contractor_handlers import handle_editor_source_name

        mock_get.return_value = None

        msg = _make_message("Автор")
        state = _make_state()

        result = asyncio.run(handle_editor_source_name(msg, state))

        assert result == "done"
        assert msg.answer.call_args[0][0] == replies.lookup.not_found


# ===================================================================
#  handle_sign_doc
# ===================================================================

class TestHandleSignDoc:

    @patch("telegram_bot.handlers.contractor_handlers._deliver_or_start_invoice", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.contractor_handlers.get_current_contractor", new_callable=AsyncMock)
    def test_linked_contractor_delivers(self, mock_get, mock_deliver):
        from telegram_bot.handlers.contractor_handlers import handle_sign_doc

        mock_get.return_value = _samoz()

        msg = _make_message("/sign")
        state = _make_state()

        asyncio.run(handle_sign_doc(msg, state))

        mock_deliver.assert_awaited_once()

    @patch("telegram_bot.handlers.contractor_handlers.get_current_contractor", new_callable=AsyncMock)
    def test_no_contractor(self, mock_get):
        from telegram_bot.handlers.contractor_handlers import handle_sign_doc

        mock_get.return_value = None

        msg = _make_message("/sign")
        state = _make_state()

        asyncio.run(handle_sign_doc(msg, state))

        msg.answer.assert_awaited()
        assert msg.answer.call_args[0][0] == replies.start.contractor


# ===================================================================
#  handle_update_payment_data
# ===================================================================

class TestHandleUpdatePaymentData:

    @patch("telegram_bot.handlers.contractor_handlers.get_current_contractor", new_callable=AsyncMock)
    def test_linked_contractor_prompts_update(self, mock_get):
        from telegram_bot.handlers.contractor_handlers import handle_update_payment_data

        mock_get.return_value = _samoz()

        msg = _make_message("/update")
        state = _make_state()

        asyncio.run(handle_update_payment_data(msg, state))

        state.set_state.assert_awaited_once_with("ContractorStates:waiting_update_data")
        msg.answer.assert_awaited()

    @patch("telegram_bot.handlers.contractor_handlers.get_current_contractor", new_callable=AsyncMock)
    def test_no_contractor(self, mock_get):
        from telegram_bot.handlers.contractor_handlers import handle_update_payment_data

        mock_get.return_value = None

        msg = _make_message("/update")
        state = _make_state()

        asyncio.run(handle_update_payment_data(msg, state))

        msg.answer.assert_awaited()
        assert msg.answer.call_args[0][0] == replies.start.contractor


# ===================================================================
#  _forward_to_admins
# ===================================================================

class TestForwardToAdmins:

    @patch("telegram_bot.handlers.contractor_handlers.ADMIN_TELEGRAM_IDS", [111, 222])
    @patch("telegram_bot.handlers.contractor_handlers.bot", new_callable=AsyncMock)
    def test_sends_to_all_admins(self, mock_bot):
        from telegram_bot.handlers.contractor_handlers import _forward_to_admins

        asyncio.run(_forward_to_admins(
            "Иван Иванов, email: ivan@test.com",
            ContractorType.SAMOZANYATY,
            {"name_ru": "Иван Иванов", "email": "ivan@test.com"},
        ))

        assert mock_bot.send_message.await_count == 2

    @patch("telegram_bot.handlers.contractor_handlers.ADMIN_TELEGRAM_IDS", [111])
    @patch("telegram_bot.handlers.contractor_handlers.bot", new_callable=AsyncMock)
    def test_error_silenced(self, mock_bot):
        from telegram_bot.handlers.contractor_handlers import _forward_to_admins

        mock_bot.send_message.side_effect = Exception("TG error")

        # Should not raise
        asyncio.run(_forward_to_admins("text", ContractorType.GLOBAL, {}))


# ===================================================================
#  _notify_admins_rub_invoice
# ===================================================================

class TestNotifyAdminsRubInvoice:

    @patch("telegram_bot.handlers.contractor_handlers._admin_reply_map", {})
    @patch("telegram_bot.handlers.contractor_handlers.ADMIN_TELEGRAM_IDS", [111])
    @patch("telegram_bot.handlers.contractor_handlers.bot", new_callable=AsyncMock)
    def test_sends_and_populates_map(self, mock_bot):
        from telegram_bot.handlers.contractor_handlers import _notify_admins_rub_invoice, _admin_reply_map

        contractor = _samoz(telegram="42")
        sent_msg = MagicMock()
        sent_msg.message_id = 99
        mock_bot.send_document.return_value = sent_msg

        asyncio.run(_notify_admins_rub_invoice(
            b"pdf", "test.pdf", contractor, "2026-02", 5000,
        ))

        mock_bot.send_document.assert_awaited_once()
        assert (111, 99) in _admin_reply_map
