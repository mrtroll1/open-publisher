import asyncio
from dataclasses import dataclass, field
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from common.models import (
    Currency,
    GlobalContractor,
    Invoice,
    InvoiceStatus,
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


def _make_message(text: str = "", chat_id: int = 100, user_id: int = 42) -> AsyncMock:
    msg = AsyncMock()
    msg.text = text
    msg.caption = None
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


def _make_state() -> AsyncMock:
    state = AsyncMock()
    state.get_state.return_value = None
    return state


def _invoice(**overrides) -> Invoice:
    kwargs = dict(
        contractor_id="g1", contractor_name="Test Global",
        invoice_number=1, month="2026-02",
        amount=Decimal("1000"), currency=Currency.EUR,
        status=InvoiceStatus.DRAFT,
    )
    kwargs.update(overrides)
    return Invoice(**kwargs)


@dataclass
class FakeInvoiceResult:
    pdf_bytes: bytes = b"pdf-data"
    invoice: Invoice = field(default_factory=_invoice)


@dataclass
class FakeBatchResult:
    generated: list = field(default_factory=list)
    counts: dict = field(default_factory=lambda: {"global": 0, "ip": 0, "samozanyaty": 0})
    errors: list = field(default_factory=list)
    skipped: int = 0
    total: int = 0


# ===================================================================
#  cmd_generate
# ===================================================================

class TestCmdGenerate:

    def test_no_args_shows_usage(self):
        from telegram_bot.handlers.admin_handlers import cmd_generate

        msg = _make_message("/generate")
        asyncio.run(cmd_generate(msg, _make_state()))

        msg.answer.assert_awaited_once()
        assert msg.answer.call_args[0][0] == replies.admin.generate_usage

    @patch("telegram_bot.handlers.admin_handlers.send_typing", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers._find_contractor_or_suggest", new_callable=AsyncMock)
    def test_contractor_not_found(self, mock_find, mock_typing):
        from telegram_bot.handlers.admin_handlers import cmd_generate

        mock_find.return_value = None

        msg = _make_message("/generate неизвестный")
        asyncio.run(cmd_generate(msg, _make_state()))

        mock_find.assert_awaited_once()

    @patch("telegram_bot.handlers.admin_handlers.create_and_save_invoice")
    @patch("telegram_bot.handlers.admin_handlers.fetch_articles")
    @patch("telegram_bot.handlers.admin_handlers.read_budget_amounts")
    @patch("telegram_bot.handlers.admin_handlers.prev_month", return_value="2026-02")
    @patch("telegram_bot.handlers.admin_handlers.send_typing", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers._find_contractor_or_suggest", new_callable=AsyncMock)
    def test_not_in_budget(self, mock_find, mock_typing, mock_month, mock_budget, mock_fetch, mock_create):
        from telegram_bot.handlers.admin_handlers import cmd_generate

        contractor = _samoz()
        mock_find.return_value = contractor
        mock_budget.return_value = {}  # Empty budget

        msg = _make_message("/generate Тест")
        asyncio.run(cmd_generate(msg, _make_state()))

        msg.answer.assert_awaited()
        last_call = msg.answer.call_args[0][0]
        assert contractor.display_name in last_call

    @patch("telegram_bot.handlers.admin_handlers.create_and_save_invoice")
    @patch("telegram_bot.handlers.admin_handlers.fetch_articles")
    @patch("telegram_bot.handlers.admin_handlers.read_budget_amounts")
    @patch("telegram_bot.handlers.admin_handlers.prev_month", return_value="2026-02")
    @patch("telegram_bot.handlers.admin_handlers.send_typing", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers._find_contractor_or_suggest", new_callable=AsyncMock)
    def test_zero_amount(self, mock_find, mock_typing, mock_month, mock_budget, mock_fetch, mock_create):
        from telegram_bot.handlers.admin_handlers import cmd_generate

        contractor = _samoz()
        mock_find.return_value = contractor
        mock_budget.return_value = {contractor.display_name.lower().strip(): (0, 0, "")}

        msg = _make_message("/generate Тест")
        asyncio.run(cmd_generate(msg, _make_state()))

        last_call = msg.answer.call_args[0][0]
        assert "не указана" in last_call.lower() or "2026-02" in last_call

    @patch("telegram_bot.handlers.admin_handlers._admin_reply_map", {})
    @patch("telegram_bot.handlers.admin_handlers.create_and_save_invoice")
    @patch("telegram_bot.handlers.admin_handlers.fetch_articles")
    @patch("telegram_bot.handlers.admin_handlers.read_budget_amounts")
    @patch("telegram_bot.handlers.admin_handlers.prev_month", return_value="2026-02")
    @patch("telegram_bot.handlers.admin_handlers.send_typing", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers._find_contractor_or_suggest", new_callable=AsyncMock)
    def test_successful_rub_generation(self, mock_find, mock_typing, mock_month, mock_budget, mock_fetch, mock_create):
        from telegram_bot.handlers.admin_handlers import cmd_generate, _admin_reply_map

        contractor = _samoz(telegram="12345")
        mock_find.return_value = contractor
        mock_budget.return_value = {contractor.display_name.lower().strip(): (0, 5000, "")}
        mock_fetch.return_value = []
        mock_create.return_value = FakeInvoiceResult(
            invoice=_invoice(currency=Currency.RUB, amount=Decimal("5000")),
        )

        msg = _make_message("/generate Тест")
        sent_doc = MagicMock()
        sent_doc.message_id = 50
        msg.answer_document.return_value = sent_doc

        asyncio.run(cmd_generate(msg, _make_state()))

        msg.answer_document.assert_awaited_once()
        # Should populate _admin_reply_map
        assert (100, 50) in _admin_reply_map

    @patch("telegram_bot.handlers.admin_handlers.create_and_save_invoice")
    @patch("telegram_bot.handlers.admin_handlers.fetch_articles")
    @patch("telegram_bot.handlers.admin_handlers.read_budget_amounts")
    @patch("telegram_bot.handlers.admin_handlers.prev_month", return_value="2026-02")
    @patch("telegram_bot.handlers.admin_handlers.send_typing", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers._find_contractor_or_suggest", new_callable=AsyncMock)
    def test_successful_eur_generation(self, mock_find, mock_typing, mock_month, mock_budget, mock_fetch, mock_create):
        from telegram_bot.handlers.admin_handlers import cmd_generate

        contractor = _global()
        mock_find.return_value = contractor
        mock_budget.return_value = {contractor.display_name.lower().strip(): (1000, 0, "")}
        mock_fetch.return_value = []
        mock_create.return_value = FakeInvoiceResult()

        msg = _make_message("/generate Test")
        asyncio.run(cmd_generate(msg, _make_state()))

        msg.answer_document.assert_awaited_once()

    @patch("telegram_bot.handlers.admin_handlers.create_and_save_invoice")
    @patch("telegram_bot.handlers.admin_handlers.fetch_articles")
    @patch("telegram_bot.handlers.admin_handlers.read_budget_amounts")
    @patch("telegram_bot.handlers.admin_handlers.prev_month", return_value="2026-02")
    @patch("telegram_bot.handlers.admin_handlers.send_typing", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers._find_contractor_or_suggest", new_callable=AsyncMock)
    def test_generation_error(self, mock_find, mock_typing, mock_month, mock_budget, mock_fetch, mock_create):
        from telegram_bot.handlers.admin_handlers import cmd_generate

        contractor = _samoz()
        mock_find.return_value = contractor
        mock_budget.return_value = {contractor.display_name.lower().strip(): (0, 5000, "")}
        mock_fetch.return_value = []
        mock_create.side_effect = Exception("Generation failed")

        msg = _make_message("/generate Тест")
        asyncio.run(cmd_generate(msg, _make_state()))

        last_call = msg.answer.call_args[0][0]
        assert "Generation failed" in last_call

    @patch("telegram_bot.handlers.admin_handlers.create_and_save_invoice")
    @patch("telegram_bot.handlers.admin_handlers.fetch_articles")
    @patch("telegram_bot.handlers.admin_handlers.read_budget_amounts")
    @patch("telegram_bot.handlers.admin_handlers.prev_month", return_value="2026-02")
    @patch("telegram_bot.handlers.admin_handlers.send_typing", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers._find_contractor_or_suggest", new_callable=AsyncMock)
    def test_debug_mode(self, mock_find, mock_typing, mock_month, mock_budget, mock_fetch, mock_create):
        from telegram_bot.handlers.admin_handlers import cmd_generate

        contractor = _samoz(telegram="12345")
        mock_find.return_value = contractor
        mock_budget.return_value = {contractor.display_name.lower().strip(): (0, 5000, "")}
        mock_fetch.return_value = []
        mock_create.return_value = FakeInvoiceResult(
            invoice=_invoice(currency=Currency.RUB),
        )

        msg = _make_message("/generate debug Тест")
        asyncio.run(cmd_generate(msg, _make_state()))

        msg.answer_document.assert_awaited_once()
        caption = msg.answer_document.call_args[1]["caption"]
        assert "[DEBUG]" in caption


# ===================================================================
#  cmd_budget
# ===================================================================

class TestCmdBudget:

    @patch("telegram_bot.handlers.admin_handlers.send_typing", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.create_compute_budget")
    def test_success(self, mock_create, mock_typing):
        from telegram_bot.handlers.admin_handlers import cmd_budget

        uc = MagicMock()
        uc.execute.return_value = "https://docs.google.com/spreadsheets/123"
        mock_create.return_value = uc

        msg = _make_message("/budget 2026-01")
        asyncio.run(cmd_budget(msg, _make_state()))

        uc.execute.assert_called_once_with("2026-01")
        calls = [c[0][0] for c in msg.answer.call_args_list]
        assert any("https://docs.google.com/spreadsheets/123" in c for c in calls)

    @patch("telegram_bot.handlers.admin_handlers.send_typing", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.create_compute_budget")
    @patch("telegram_bot.handlers.admin_handlers.prev_month", return_value="2026-02")
    def test_default_month(self, mock_prev, mock_create, mock_typing):
        from telegram_bot.handlers.admin_handlers import cmd_budget

        uc = MagicMock()
        uc.execute.return_value = "http://url"
        mock_create.return_value = uc

        msg = _make_message("/budget")
        asyncio.run(cmd_budget(msg, _make_state()))

        uc.execute.assert_called_once_with("2026-02")

    @patch("telegram_bot.handlers.admin_handlers.send_typing", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.create_compute_budget")
    def test_error(self, mock_create, mock_typing):
        from telegram_bot.handlers.admin_handlers import cmd_budget

        uc = MagicMock()
        uc.execute.side_effect = Exception("Sheet error")
        mock_create.return_value = uc

        msg = _make_message("/budget 2026-01")
        asyncio.run(cmd_budget(msg, _make_state()))

        last_call = msg.answer.call_args[0][0]
        assert "Sheet error" in last_call


# ===================================================================
#  cmd_generate_invoices
# ===================================================================

class TestCmdGenerateInvoices:

    @patch("telegram_bot.handlers.admin_handlers.send_typing", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.create_generate_batch_invoices")
    @patch("telegram_bot.handlers.admin_handlers.get_contractors", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.prev_month", return_value="2026-02")
    def test_no_results(self, mock_month, mock_get, mock_create, mock_typing):
        from telegram_bot.handlers.admin_handlers import cmd_generate_invoices

        mock_get.return_value = []
        batch = FakeBatchResult(total=0)
        mock_create.return_value.execute.return_value = batch

        msg = _make_message("/generate_invoices")
        status_msg = AsyncMock()
        msg.answer.return_value = status_msg

        asyncio.run(cmd_generate_invoices(msg, _make_state()))

        status_msg.edit_text.assert_awaited_once()
        text = status_msg.edit_text.call_args[0][0]
        assert "2026-02" in text

    @patch("telegram_bot.handlers.admin_handlers._admin_reply_map", {})
    @patch("telegram_bot.handlers.admin_handlers.send_typing", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.create_generate_batch_invoices")
    @patch("telegram_bot.handlers.admin_handlers.get_contractors", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.prev_month", return_value="2026-02")
    def test_with_results(self, mock_month, mock_get, mock_create, mock_typing):
        from telegram_bot.handlers.admin_handlers import cmd_generate_invoices

        mock_get.return_value = []
        inv = _invoice(currency=Currency.RUB)
        contractor = _samoz(telegram="12345")
        batch = FakeBatchResult(
            total=1,
            generated=[(b"pdf", contractor, inv)],
            counts={"global": 0, "ip": 0, "samozanyaty": 1},
        )
        mock_create.return_value.execute.return_value = batch

        msg = _make_message("/generate_invoices")
        status_msg = AsyncMock()
        msg.answer.return_value = status_msg
        sent_doc = MagicMock()
        sent_doc.message_id = 55
        msg.answer_document.return_value = sent_doc

        asyncio.run(cmd_generate_invoices(msg, _make_state()))

        msg.answer_document.assert_awaited()

    @patch("telegram_bot.handlers.admin_handlers.send_typing", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.create_generate_batch_invoices")
    @patch("telegram_bot.handlers.admin_handlers.get_contractors", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.prev_month", return_value="2026-02")
    def test_value_error(self, mock_month, mock_get, mock_create, mock_typing):
        from telegram_bot.handlers.admin_handlers import cmd_generate_invoices

        mock_get.return_value = []
        mock_create.return_value.execute.side_effect = ValueError("Bad budget")

        msg = _make_message("/generate_invoices")
        status_msg = AsyncMock()
        msg.answer.return_value = status_msg

        asyncio.run(cmd_generate_invoices(msg, _make_state()))

        status_msg.edit_text.assert_awaited_once_with("Bad budget")

    @patch("telegram_bot.handlers.admin_handlers.send_typing", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.create_generate_batch_invoices")
    @patch("telegram_bot.handlers.admin_handlers.get_contractors", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.prev_month", return_value="2026-02")
    def test_with_errors_in_batch(self, mock_month, mock_get, mock_create, mock_typing):
        from telegram_bot.handlers.admin_handlers import cmd_generate_invoices

        mock_get.return_value = []
        batch = FakeBatchResult(
            total=2,
            generated=[],
            counts={"global": 0, "ip": 0, "samozanyaty": 0},
            errors=["Contractor X: failed"],
        )
        mock_create.return_value.execute.return_value = batch

        msg = _make_message("/generate_invoices")
        status_msg = AsyncMock()
        msg.answer.return_value = status_msg

        asyncio.run(cmd_generate_invoices(msg, _make_state()))

        # Should include errors in the reply
        all_texts = " ".join(c[0][0] for c in msg.answer.call_args_list)
        assert "Contractor X: failed" in all_texts


# ===================================================================
#  cmd_send_global_invoices
# ===================================================================

class TestCmdSendGlobalInvoices:

    @patch("telegram_bot.handlers.admin_handlers.send_typing", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.load_invoices")
    @patch("telegram_bot.handlers.admin_handlers.prev_month", return_value="2026-02")
    def test_no_draft_global(self, mock_month, mock_load, mock_typing):
        from telegram_bot.handlers.admin_handlers import cmd_send_global_invoices

        mock_load.return_value = []

        msg = _make_message("/send_global_invoices")
        asyncio.run(cmd_send_global_invoices(msg, _make_state()))

        msg.answer.assert_awaited_once()
        assert "2026-02" in msg.answer.call_args[0][0]

    @patch("telegram_bot.handlers.admin_handlers.update_invoice_status")
    @patch("telegram_bot.handlers.admin_handlers.export_pdf")
    @patch("telegram_bot.handlers.admin_handlers.find_contractor_by_id")
    @patch("telegram_bot.handlers.admin_handlers.bot", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.get_contractors", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.send_typing", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.load_invoices")
    @patch("telegram_bot.handlers.admin_handlers.prev_month", return_value="2026-02")
    def test_sends_to_contractor(
        self, mock_month, mock_load, mock_typing, mock_get, mock_bot,
        mock_find, mock_export, mock_update,
    ):
        from telegram_bot.handlers.admin_handlers import cmd_send_global_invoices

        inv = _invoice(doc_id="doc123")
        mock_load.return_value = [inv]
        contractor = _global(telegram="999")
        mock_get.return_value = [contractor]
        mock_find.return_value = contractor
        mock_export.return_value = b"pdf-bytes"

        msg = _make_message("/send_global_invoices")
        asyncio.run(cmd_send_global_invoices(msg, _make_state()))

        mock_bot.send_document.assert_awaited_once()
        mock_update.assert_called_once()

    @patch("telegram_bot.handlers.admin_handlers.export_pdf")
    @patch("telegram_bot.handlers.admin_handlers.find_contractor_by_id")
    @patch("telegram_bot.handlers.admin_handlers.bot", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.get_contractors", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.send_typing", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.load_invoices")
    @patch("telegram_bot.handlers.admin_handlers.prev_month", return_value="2026-02")
    def test_no_telegram_reports_error(
        self, mock_month, mock_load, mock_typing, mock_get, mock_bot,
        mock_find, mock_export,
    ):
        from telegram_bot.handlers.admin_handlers import cmd_send_global_invoices

        inv = _invoice(doc_id="doc123")
        mock_load.return_value = [inv]
        contractor = _global(telegram="")  # No Telegram
        mock_get.return_value = [contractor]
        mock_find.return_value = contractor
        mock_export.return_value = b"pdf-bytes"

        msg = _make_message("/send_global_invoices")
        asyncio.run(cmd_send_global_invoices(msg, _make_state()))

        text = msg.answer.call_args[0][0]
        assert "не привязан" in text.lower() or "Telegram" in text

    @patch("telegram_bot.handlers.admin_handlers.find_contractor_by_id")
    @patch("telegram_bot.handlers.admin_handlers.bot", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.get_contractors", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.send_typing", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.load_invoices")
    @patch("telegram_bot.handlers.admin_handlers.prev_month", return_value="2026-02")
    def test_no_doc_id_reports_error(
        self, mock_month, mock_load, mock_typing, mock_get, mock_bot, mock_find,
    ):
        from telegram_bot.handlers.admin_handlers import cmd_send_global_invoices

        inv = _invoice(doc_id="")  # No doc_id
        mock_load.return_value = [inv]
        contractor = _global(telegram="999")
        mock_get.return_value = [contractor]
        mock_find.return_value = contractor

        msg = _make_message("/send_global_invoices")
        asyncio.run(cmd_send_global_invoices(msg, _make_state()))

        text = msg.answer.call_args[0][0]
        assert "doc_id" in text.lower() or "ошибк" in text.lower()


# ===================================================================
#  cmd_orphan_contractors
# ===================================================================

class TestCmdOrphanContractors:

    @patch("telegram_bot.handlers.admin_handlers.read_budget_amounts")
    @patch("telegram_bot.handlers.admin_handlers.get_contractors", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.prev_month", return_value="2026-02")
    @patch("telegram_bot.handlers.admin_handlers.send_typing", new_callable=AsyncMock)
    def test_no_orphans(self, mock_typing, mock_month, mock_get, mock_budget):
        from telegram_bot.handlers.admin_handlers import cmd_orphan_contractors

        contractor = _samoz()
        mock_get.return_value = [contractor]
        mock_budget.return_value = {contractor.display_name.lower().strip(): (0, 5000, "")}

        msg = _make_message("/orphan_contractors")
        asyncio.run(cmd_orphan_contractors(msg, _make_state()))

        text = msg.answer.call_args[0][0]
        assert "совпадают" in text.lower()

    @patch("telegram_bot.handlers.admin_handlers.read_budget_amounts")
    @patch("telegram_bot.handlers.admin_handlers.get_contractors", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.prev_month", return_value="2026-02")
    @patch("telegram_bot.handlers.admin_handlers.send_typing", new_callable=AsyncMock)
    def test_with_orphans(self, mock_typing, mock_month, mock_get, mock_budget):
        from telegram_bot.handlers.admin_handlers import cmd_orphan_contractors

        mock_get.return_value = []
        mock_budget.return_value = {"иван иванов": (0, 5000, ""), "мария петрова": (0, 3000, "")}

        msg = _make_message("/orphan_contractors")
        asyncio.run(cmd_orphan_contractors(msg, _make_state()))

        text = msg.answer.call_args[0][0]
        assert "2" in text  # 2 orphans
        assert "иван иванов" in text
        assert "мария петрова" in text


# ===================================================================
#  cmd_chatid
# ===================================================================

class TestCmdChatid:

    def test_returns_chat_id(self):
        from telegram_bot.handlers.admin_handlers import cmd_chatid

        msg = _make_message("/chatid", chat_id=777)
        asyncio.run(cmd_chatid(msg, _make_state()))

        msg.answer.assert_awaited_once()
        text = msg.answer.call_args[0][0]
        assert "777" in text


# ===================================================================
#  cmd_upload_to_airtable
# ===================================================================

class TestCmdUploadToAirtable:

    def test_no_document_shows_usage(self):
        from telegram_bot.handlers.admin_handlers import cmd_upload_to_airtable

        msg = _make_message("/upload_to_airtable 95.5")
        msg.document = None
        asyncio.run(cmd_upload_to_airtable(msg, _make_state()))

        msg.answer.assert_awaited_once()
        assert msg.answer.call_args[0][0] == replies.admin.upload_usage

    def test_no_rate_arg_shows_usage(self):
        from telegram_bot.handlers.admin_handlers import cmd_upload_to_airtable

        msg = _make_message("/upload_to_airtable")
        msg.document = MagicMock()
        asyncio.run(cmd_upload_to_airtable(msg, _make_state()))

        msg.answer.assert_awaited_once()
        assert msg.answer.call_args[0][0] == replies.admin.upload_usage

    def test_invalid_rate_shows_usage(self):
        from telegram_bot.handlers.admin_handlers import cmd_upload_to_airtable

        msg = _make_message("/upload_to_airtable abc")
        msg.document = MagicMock()
        asyncio.run(cmd_upload_to_airtable(msg, _make_state()))

        msg.answer.assert_awaited_once()
        assert msg.answer.call_args[0][0] == replies.admin.upload_usage

    @patch("telegram_bot.handlers.admin_handlers.os.unlink")
    @patch("telegram_bot.handlers.admin_handlers.create_parse_bank_statement")
    @patch("telegram_bot.handlers.admin_handlers.bot", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.send_typing", new_callable=AsyncMock)
    def test_successful_upload(self, mock_typing, mock_bot, mock_create, mock_unlink):
        from telegram_bot.handlers.admin_handlers import cmd_upload_to_airtable

        uc = MagicMock()
        uc.execute.return_value = [MagicMock(comment="OK"), MagicMock(comment="NEEDS REVIEW")]
        mock_create.return_value = uc

        file_mock = MagicMock()
        file_mock.file_path = "/tmp/test.csv"
        mock_bot.get_file.return_value = file_mock
        file_bytes_mock = MagicMock()
        file_bytes_mock.read.return_value = b"csv-data"
        mock_bot.download_file.return_value = file_bytes_mock

        msg = _make_message("/upload_to_airtable 95.5")
        msg.document = MagicMock()
        msg.document.file_id = "file-123"

        asyncio.run(cmd_upload_to_airtable(msg, _make_state()))

        calls = [c[0][0] for c in msg.answer.call_args_list]
        assert any("2" in c and "Airtable" in c for c in calls)

    @patch("telegram_bot.handlers.admin_handlers.os.unlink")
    @patch("telegram_bot.handlers.admin_handlers.create_parse_bank_statement")
    @patch("telegram_bot.handlers.admin_handlers.bot", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.send_typing", new_callable=AsyncMock)
    def test_upload_error(self, mock_typing, mock_bot, mock_create, mock_unlink):
        from telegram_bot.handlers.admin_handlers import cmd_upload_to_airtable

        mock_create.return_value.execute.side_effect = Exception("Parse error")

        file_mock = MagicMock()
        file_mock.file_path = "/tmp/test.csv"
        mock_bot.get_file.return_value = file_mock
        file_bytes_mock = MagicMock()
        file_bytes_mock.read.return_value = b"csv-data"
        mock_bot.download_file.return_value = file_bytes_mock

        msg = _make_message("/upload_to_airtable 95.5")
        msg.document = MagicMock()
        msg.document.file_id = "file-123"

        asyncio.run(cmd_upload_to_airtable(msg, _make_state()))

        last_call = msg.answer.call_args[0][0]
        assert "Parse error" in last_call

    @patch("telegram_bot.handlers.admin_handlers.os.unlink")
    @patch("telegram_bot.handlers.admin_handlers.create_parse_bank_statement")
    @patch("telegram_bot.handlers.admin_handlers.bot", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.send_typing", new_callable=AsyncMock)
    def test_tmp_file_cleaned_up(self, mock_typing, mock_bot, mock_create, mock_unlink):
        from telegram_bot.handlers.admin_handlers import cmd_upload_to_airtable

        mock_create.return_value.execute.return_value = []

        file_mock = MagicMock()
        file_mock.file_path = "/tmp/test.csv"
        mock_bot.get_file.return_value = file_mock
        file_bytes_mock = MagicMock()
        file_bytes_mock.read.return_value = b"csv-data"
        mock_bot.download_file.return_value = file_bytes_mock

        msg = _make_message("/upload_to_airtable 95.5")
        msg.document = MagicMock()
        msg.document.file_id = "file-123"

        asyncio.run(cmd_upload_to_airtable(msg, _make_state()))

        mock_unlink.assert_called_once()


# ===================================================================
#  cmd_send_legium_links
# ===================================================================

class TestCmdSendLegiumLinks:

    @patch("telegram_bot.handlers.admin_handlers.send_typing", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.load_invoices")
    @patch("telegram_bot.handlers.admin_handlers.prev_month", return_value="2026-02")
    def test_no_pending(self, mock_month, mock_load, mock_typing):
        from telegram_bot.handlers.admin_handlers import cmd_send_legium_links

        mock_load.return_value = []

        msg = _make_message("/send_legium_links")
        asyncio.run(cmd_send_legium_links(msg, _make_state()))

        msg.answer.assert_awaited_once()
        assert "2026-02" in msg.answer.call_args[0][0]

    @patch("telegram_bot.handlers.admin_handlers.update_invoice_status")
    @patch("telegram_bot.handlers.admin_handlers.prepare_existing_invoice")
    @patch("telegram_bot.handlers.admin_handlers.find_contractor_by_id")
    @patch("telegram_bot.handlers.admin_handlers.bot", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.get_contractors", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.send_typing", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.load_invoices")
    @patch("telegram_bot.handlers.admin_handlers.prev_month", return_value="2026-02")
    def test_sends_with_pdf(
        self, mock_month, mock_load, mock_typing, mock_get, mock_bot,
        mock_find, mock_prepare, mock_update,
    ):
        from telegram_bot.handlers.admin_handlers import cmd_send_legium_links

        inv = _invoice(
            currency=Currency.RUB, status=InvoiceStatus.DRAFT,
            contractor_id="s1",
        )
        inv.legium_link = "https://legium.io/doc/123"
        mock_load.return_value = [inv]
        contractor = _samoz(telegram="999")
        mock_get.return_value = [contractor]
        mock_find.return_value = contractor

        from backend.domain.use_cases.prepare_invoice import PreparedInvoice
        mock_prepare.return_value = PreparedInvoice(
            pdf_bytes=b"pdf", invoice=inv, contractor=contractor,
        )

        msg = _make_message("/send_legium_links")
        asyncio.run(cmd_send_legium_links(msg, _make_state()))

        mock_bot.send_document.assert_awaited_once()
        mock_update.assert_called_once()

    @patch("telegram_bot.handlers.admin_handlers.find_contractor_by_id")
    @patch("telegram_bot.handlers.admin_handlers.bot", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.get_contractors", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.send_typing", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.load_invoices")
    @patch("telegram_bot.handlers.admin_handlers.prev_month", return_value="2026-02")
    def test_no_telegram_reports_error(
        self, mock_month, mock_load, mock_typing, mock_get, mock_bot, mock_find,
    ):
        from telegram_bot.handlers.admin_handlers import cmd_send_legium_links

        inv = _invoice(currency=Currency.RUB, status=InvoiceStatus.DRAFT)
        inv.legium_link = "https://legium.io/doc/123"
        mock_load.return_value = [inv]
        contractor = _samoz(telegram="")
        mock_get.return_value = [contractor]
        mock_find.return_value = contractor

        msg = _make_message("/send_legium_links")
        asyncio.run(cmd_send_legium_links(msg, _make_state()))

        text = msg.answer.call_args[0][0]
        assert "не привязан" in text.lower() or "Telegram" in text


# ===================================================================
#  cmd_extract_knowledge
# ===================================================================

class TestCmdExtractKnowledge:

    @patch("telegram_bot.handlers.admin_handlers.send_typing", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.ExtractConversationKnowledge")
    def test_default_hours(self, mock_cls, mock_typing):
        from telegram_bot.handlers.admin_handlers import cmd_extract_knowledge

        instance = MagicMock()
        instance.execute.return_value = ["id-1", "id-2"]
        mock_cls.return_value = instance

        msg = _make_message("/extract_knowledge")
        asyncio.run(cmd_extract_knowledge(msg, _make_state()))

        instance.execute.assert_called_once_with(100, since_hours=24)
        calls = [c[0][0] for c in msg.answer.call_args_list]
        assert any("2" in c for c in calls)

    @patch("telegram_bot.handlers.admin_handlers.send_typing", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.ExtractConversationKnowledge")
    def test_custom_hours(self, mock_cls, mock_typing):
        from telegram_bot.handlers.admin_handlers import cmd_extract_knowledge

        instance = MagicMock()
        instance.execute.return_value = []
        mock_cls.return_value = instance

        msg = _make_message("/extract_knowledge 48")
        asyncio.run(cmd_extract_knowledge(msg, _make_state()))

        instance.execute.assert_called_once_with(100, since_hours=48)

    def test_invalid_hours_shows_usage(self):
        from telegram_bot.handlers.admin_handlers import cmd_extract_knowledge

        msg = _make_message("/extract_knowledge abc")
        asyncio.run(cmd_extract_knowledge(msg, _make_state()))

        msg.answer.assert_awaited_once()
        assert msg.answer.call_args[0][0] == replies.admin.extract_knowledge_usage

    @patch("telegram_bot.handlers.admin_handlers.send_typing", new_callable=AsyncMock)
    @patch("telegram_bot.handlers.admin_handlers.ExtractConversationKnowledge")
    def test_extraction_error(self, mock_cls, mock_typing):
        from telegram_bot.handlers.admin_handlers import cmd_extract_knowledge

        instance = MagicMock()
        instance.execute.side_effect = Exception("DB error")
        mock_cls.return_value = instance

        msg = _make_message("/extract_knowledge")
        asyncio.run(cmd_extract_knowledge(msg, _make_state()))

        last_call = msg.answer.call_args[0][0]
        assert "DB error" in last_call
