from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from backend.commands.invoice.generate import GenerateInvoice, InvoiceResult
from common.models import (
    ArticleEntry,
    Currency,
    GlobalContractor,
    IPContractor,
    InvoiceStatus,
    RoleCode,
    SamozanyatyContractor,
)


# ---------------------------------------------------------------------------
#  Contractor factories
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
        bank_name="Банк", bank_account="40802", bik="044525225",
        corr_account="30101810400000000225",
        passport_series="4500", passport_number="111222",
        passport_issued_by="ОВД", passport_issued_date="01.01.2020",
        passport_code="770-001", ogrnip="12345678901234",
    )
    kwargs.update(overrides)
    return IPContractor(**kwargs)


def _articles(n: int = 2) -> list[ArticleEntry]:
    return [ArticleEntry(article_id=f"art{i}") for i in range(1, n + 1)]


# ---------------------------------------------------------------------------
#  Patch paths
# ---------------------------------------------------------------------------

_PATCH_DOCS = "backend.commands.invoice.generate.DocsGateway"
_PATCH_DRIVE = "backend.commands.invoice.generate.DriveGateway"
_PATCH_INCREMENT = "backend.commands.invoice.generate.increment_invoice_number"
_PATCH_SAVE = "backend.commands.invoice.generate.save_invoice"


def _make_gen(mock_docs, mock_drive) -> GenerateInvoice:
    """Build a GenerateInvoice with mocked gateways."""
    gen = GenerateInvoice.__new__(GenerateInvoice)
    gen._docs = mock_docs
    gen._drive = mock_drive
    return gen


def _setup_docs(mock_docs, pdf_bytes=b"%PDF-fake") -> None:
    mock_docs.copy_template.return_value = "doc123"
    mock_docs.export_pdf.return_value = pdf_bytes
    mock_docs.format_date_en = staticmethod(lambda d: d.strftime("%d.%m.%Y"))
    mock_docs.format_date_ru = staticmethod(
        lambda d: f"\u00ab{d.day:02d}\u00bb test {d.year} \u0433.",
    )


# ===================================================================
#  Global contractor
# ===================================================================

class TestGenerateGlobalInvoice:

    def test_basic_global_invoice(self):
        docs = MagicMock()
        drive = MagicMock()
        _setup_docs(docs)
        drive.get_contractor_folder.return_value = "folder1"
        drive.upload_invoice_pdf.return_value = "https://drive.google.com/link"
        gen = _make_gen(docs, drive)

        with patch(_PATCH_SAVE) as save_mock:
            result = gen.create_and_save(
                _global(), "2026-01", Decimal("500"), _articles(),
                invoice_date=date(2026, 1, 15),
            )

        assert isinstance(result, InvoiceResult)
        assert result.pdf_bytes == b"%PDF-fake"
        assert result.invoice.contractor_id == "g1"
        assert result.invoice.amount == Decimal("500")
        assert result.invoice.currency == Currency.EUR
        assert result.invoice.doc_id == "doc123"
        assert result.invoice.gdrive_path == "https://drive.google.com/link"
        # Global = EUR, so invoice_number should be 0 (no increment)
        assert result.invoice.invoice_number == 0
        save_mock.assert_called_once()

    def test_global_uses_correct_template_id(self):
        docs = MagicMock()
        drive = MagicMock()
        _setup_docs(docs)
        drive.get_contractor_folder.return_value = "folder1"
        drive.upload_invoice_pdf.return_value = ""
        gen = _make_gen(docs, drive)

        with patch(_PATCH_SAVE), \
             patch("backend.commands.invoice.generate.TEMPLATE_GLOBAL_ID", "tmpl_global"), \
             patch("backend.commands.invoice.generate.TEMPLATE_GLOBAL_PHOTO_ID", "tmpl_global_photo"):
            gen.create_and_save(
                _global(), "2026-01", Decimal("100"), _articles(),
                invoice_date=date(2026, 1, 1),
            )
            docs.copy_template.assert_called_once()
            assert docs.copy_template.call_args[0][0] == "tmpl_global"

    def test_global_photographer_uses_photo_template(self):
        docs = MagicMock()
        drive = MagicMock()
        _setup_docs(docs)
        drive.get_contractor_folder.return_value = "folder1"
        drive.upload_invoice_pdf.return_value = ""
        gen = _make_gen(docs, drive)

        with patch(_PATCH_SAVE), \
             patch("backend.commands.invoice.generate.TEMPLATE_GLOBAL_ID", "tmpl_global"), \
             patch("backend.commands.invoice.generate.TEMPLATE_GLOBAL_PHOTO_ID", "tmpl_global_photo"):
            gen.create_and_save(
                _global(is_photographer=True), "2026-01", Decimal("100"), _articles(),
                invoice_date=date(2026, 1, 1),
            )
            assert docs.copy_template.call_args[0][0] == "tmpl_global_photo"

    def test_global_replacements_contain_expected_keys(self):
        docs = MagicMock()
        drive = MagicMock()
        _setup_docs(docs)
        drive.get_contractor_folder.return_value = "folder1"
        drive.upload_invoice_pdf.return_value = ""
        gen = _make_gen(docs, drive)

        with patch(_PATCH_SAVE):
            gen.create_and_save(
                _global(name_en="John Doe", address="123 St", swift="ABCDEF"),
                "2026-01", Decimal("750.50"), _articles(3),
                invoice_date=date(2026, 1, 15),
            )

        replacements = docs.replace_text.call_args[0][1]
        assert replacements["{{NAME}}"] == "John Doe"
        assert replacements["{{ADDRESS}}"] == "123 St"
        assert replacements["{{BIC_SWIFT}}"] == "ABCDEF"
        assert replacements["{{AMOUNT}}"] == "750.50"
        assert replacements["{{CURRENCY}}"] == "EUR"
        assert replacements["{{NUM_ARTICLES}}"] == "3"
        assert replacements["{{INVOICE_DATE}}"] == "15.01.2026"

    def test_global_articles_table_inserted(self):
        docs = MagicMock()
        drive = MagicMock()
        _setup_docs(docs)
        drive.get_contractor_folder.return_value = "folder1"
        drive.upload_invoice_pdf.return_value = ""
        gen = _make_gen(docs, drive)

        articles = _articles(2)
        with patch(_PATCH_SAVE):
            gen.create_and_save(
                _global(), "2026-01", Decimal("500"), articles,
                invoice_date=date(2026, 1, 1),
            )

        docs.insert_articles_table.assert_called_once()
        call_args = docs.insert_articles_table.call_args[0]
        assert call_args[0] == "doc123"  # doc_id
        assert call_args[1] == "{{ARTICLES_TABLE}}"  # placeholder
        assert call_args[2] == articles  # articles
        assert call_args[3] == ["\u2116", "Article - Code", "Language"]
        assert call_args[4] == "Russian"


# ===================================================================
#  IP contractor
# ===================================================================

class TestGenerateIPInvoice:

    def test_ip_invoice_increments_number(self):
        docs = MagicMock()
        drive = MagicMock()
        _setup_docs(docs)
        drive.get_contractor_folder.return_value = "folder1"
        drive.upload_invoice_pdf.return_value = ""
        gen = _make_gen(docs, drive)

        with patch(_PATCH_INCREMENT, return_value=42) as inc_mock, \
             patch(_PATCH_SAVE):
            result = gen.create_and_save(
                _ip(), "2026-01", Decimal("10000"), _articles(),
                invoice_date=date(2026, 1, 15),
            )

        inc_mock.assert_called_once_with("ip1")
        assert result.invoice.invoice_number == 42

    def test_ip_uses_correct_template(self):
        docs = MagicMock()
        drive = MagicMock()
        _setup_docs(docs)
        drive.get_contractor_folder.return_value = "folder1"
        drive.upload_invoice_pdf.return_value = ""
        gen = _make_gen(docs, drive)

        with patch(_PATCH_INCREMENT, return_value=1), \
             patch(_PATCH_SAVE), \
             patch("backend.commands.invoice.generate.TEMPLATE_IP_ID", "tmpl_ip"), \
             patch("backend.commands.invoice.generate.TEMPLATE_IP_PHOTO_ID", "tmpl_ip_photo"):
            gen.create_and_save(
                _ip(), "2026-01", Decimal("10000"), _articles(),
                invoice_date=date(2026, 1, 1),
            )
            assert docs.copy_template.call_args[0][0] == "tmpl_ip"

    def test_ip_photographer_uses_photo_template(self):
        docs = MagicMock()
        drive = MagicMock()
        _setup_docs(docs)
        drive.get_contractor_folder.return_value = "folder1"
        drive.upload_invoice_pdf.return_value = ""
        gen = _make_gen(docs, drive)

        with patch(_PATCH_INCREMENT, return_value=1), \
             patch(_PATCH_SAVE), \
             patch("backend.commands.invoice.generate.TEMPLATE_IP_ID", "tmpl_ip"), \
             patch("backend.commands.invoice.generate.TEMPLATE_IP_PHOTO_ID", "tmpl_ip_photo"):
            gen.create_and_save(
                _ip(is_photographer=True), "2026-01", Decimal("10000"), _articles(),
                invoice_date=date(2026, 1, 1),
            )
            assert docs.copy_template.call_args[0][0] == "tmpl_ip_photo"

    def test_ip_replacements_contain_rub_fields(self):
        docs = MagicMock()
        drive = MagicMock()
        _setup_docs(docs)
        drive.get_contractor_folder.return_value = "folder1"
        drive.upload_invoice_pdf.return_value = ""
        gen = _make_gen(docs, drive)

        with patch(_PATCH_INCREMENT, return_value=7), \
             patch(_PATCH_SAVE):
            gen.create_and_save(
                _ip(name_ru="Иванов Иван", ogrnip="999", passport_issued_by="ОВД Москва",
                    passport_issued_date="15.03.2018", passport_code="770-001",
                    passport_series="4500", passport_number="111222",
                    bank_account="40802", bank_name="Сбербанк", bik="044525225",
                    corr_account="30101"),
                "2026-01", Decimal("15000"), _articles(),
                invoice_date=date(2026, 1, 20),
            )

        replacements = docs.replace_text.call_args[0][1]
        assert replacements["{{FULL_NAME}}"] == "Иванов Иван"
        assert replacements["{{OGRNIP}}"] == "999"
        assert replacements["{{PASSPORT_ISSUED_BY}}"] == "ОВД Москва"
        assert replacements["{{PASSPORT_ISSUED_DATE}}"] == "15.03.2018"
        assert replacements["{{PASSPORT_CODE}}"] == "770-001"
        assert replacements["{{PASSPORT_SERIES}}"] == "4500"
        assert replacements["{{PASSPORT_NUMBER}}"] == "111222"
        assert replacements["{{AMOUNT}}"] == "15000"
        assert replacements["{{INVOICE_NUMBER}}"] == "7"
        assert replacements["{{INVOICE_DAY}}"] == "20"
        assert replacements["{{INVOICE_YEAR}}"] == "2026"

    def test_ip_articles_table_uses_russian_headers(self):
        docs = MagicMock()
        drive = MagicMock()
        _setup_docs(docs)
        drive.get_contractor_folder.return_value = "folder1"
        drive.upload_invoice_pdf.return_value = ""
        gen = _make_gen(docs, drive)

        with patch(_PATCH_INCREMENT, return_value=1), \
             patch(_PATCH_SAVE):
            gen.create_and_save(
                _ip(), "2026-01", Decimal("10000"), _articles(),
                invoice_date=date(2026, 1, 1),
            )

        call_args = docs.insert_articles_table.call_args[0]
        assert call_args[3] == ["\u2116", "\u0421\u0442\u0430\u0442\u044c\u044f - \u041a\u043e\u0434", "\u0422\u0438\u043f \u041f\u0440\u043e\u0438\u0437\u0432\u0435\u0434\u0435\u043d\u0438\u044f"]
        assert call_args[4] == "\u0421\u0442\u0430\u0442\u044c\u044f"


# ===================================================================
#  Samozanyaty contractor
# ===================================================================

class TestGenerateSamozanyatyInvoice:

    def test_samozanyaty_invoice_increments_number(self):
        docs = MagicMock()
        drive = MagicMock()
        _setup_docs(docs)
        drive.get_contractor_folder.return_value = "folder1"
        drive.upload_invoice_pdf.return_value = ""
        gen = _make_gen(docs, drive)

        with patch(_PATCH_INCREMENT, return_value=5) as inc_mock, \
             patch(_PATCH_SAVE):
            result = gen.create_and_save(
                _samoz(), "2026-01", Decimal("8000"), _articles(),
                invoice_date=date(2026, 1, 10),
            )

        inc_mock.assert_called_once_with("s1")
        assert result.invoice.invoice_number == 5

    def test_samozanyaty_uses_correct_template(self):
        docs = MagicMock()
        drive = MagicMock()
        _setup_docs(docs)
        drive.get_contractor_folder.return_value = "folder1"
        drive.upload_invoice_pdf.return_value = ""
        gen = _make_gen(docs, drive)

        with patch(_PATCH_INCREMENT, return_value=1), \
             patch(_PATCH_SAVE), \
             patch("backend.commands.invoice.generate.TEMPLATE_SAMOZANYATY_ID", "tmpl_sz"), \
             patch("backend.commands.invoice.generate.TEMPLATE_SAMOZANYATY_PHOTO_ID", "tmpl_sz_photo"):
            gen.create_and_save(
                _samoz(), "2026-01", Decimal("8000"), _articles(),
                invoice_date=date(2026, 1, 1),
            )
            assert docs.copy_template.call_args[0][0] == "tmpl_sz"

    def test_samozanyaty_photographer_uses_photo_template(self):
        docs = MagicMock()
        drive = MagicMock()
        _setup_docs(docs)
        drive.get_contractor_folder.return_value = "folder1"
        drive.upload_invoice_pdf.return_value = ""
        gen = _make_gen(docs, drive)

        with patch(_PATCH_INCREMENT, return_value=1), \
             patch(_PATCH_SAVE), \
             patch("backend.commands.invoice.generate.TEMPLATE_SAMOZANYATY_ID", "tmpl_sz"), \
             patch("backend.commands.invoice.generate.TEMPLATE_SAMOZANYATY_PHOTO_ID", "tmpl_sz_photo"):
            gen.create_and_save(
                _samoz(is_photographer=True), "2026-01", Decimal("8000"), _articles(),
                invoice_date=date(2026, 1, 1),
            )
            assert docs.copy_template.call_args[0][0] == "tmpl_sz_photo"

    def test_samozanyaty_replacements_contain_inn_and_address(self):
        docs = MagicMock()
        drive = MagicMock()
        _setup_docs(docs)
        drive.get_contractor_folder.return_value = "folder1"
        drive.upload_invoice_pdf.return_value = ""
        gen = _make_gen(docs, drive)

        with patch(_PATCH_INCREMENT, return_value=3), \
             patch(_PATCH_SAVE):
            gen.create_and_save(
                _samoz(inn="999888777666", address="ул. Тестовая, д. 1"),
                "2026-01", Decimal("8000"), _articles(),
                invoice_date=date(2026, 1, 1),
            )

        replacements = docs.replace_text.call_args[0][1]
        assert replacements["{{INN}}"] == "999888777666"
        assert replacements["{{ADDRESS}}"] == "ул. Тестовая, д. 1"


# ===================================================================
#  Debug mode
# ===================================================================

class TestDebugMode:

    def test_debug_skips_increment_and_save(self):
        docs = MagicMock()
        drive = MagicMock()
        _setup_docs(docs)
        drive.get_contractor_folder.return_value = "folder1"
        drive.upload_invoice_pdf.return_value = ""
        gen = _make_gen(docs, drive)

        with patch(_PATCH_INCREMENT) as inc_mock, \
             patch(_PATCH_SAVE) as save_mock:
            result = gen.create_and_save(
                _samoz(), "2026-01", Decimal("5000"), _articles(),
                invoice_date=date(2026, 1, 1), debug=True,
            )

        inc_mock.assert_not_called()
        save_mock.assert_not_called()
        assert result.invoice.invoice_number == 0

    def test_debug_still_generates_pdf(self):
        docs = MagicMock()
        drive = MagicMock()
        _setup_docs(docs, pdf_bytes=b"debug-pdf")
        drive.get_contractor_folder.return_value = "folder1"
        drive.upload_invoice_pdf.return_value = ""
        gen = _make_gen(docs, drive)

        with patch(_PATCH_INCREMENT), patch(_PATCH_SAVE):
            result = gen.create_and_save(
                _global(), "2026-01", Decimal("100"), _articles(),
                invoice_date=date(2026, 1, 1), debug=True,
            )

        assert result.pdf_bytes == b"debug-pdf"
        docs.export_pdf.assert_called_once()

    def test_global_non_debug_does_not_increment_number(self):
        """Global contractors use EUR, so increment_invoice_number is NOT called
        even in non-debug mode."""
        docs = MagicMock()
        drive = MagicMock()
        _setup_docs(docs)
        drive.get_contractor_folder.return_value = "folder1"
        drive.upload_invoice_pdf.return_value = ""
        gen = _make_gen(docs, drive)

        with patch(_PATCH_INCREMENT) as inc_mock, \
             patch(_PATCH_SAVE):
            result = gen.create_and_save(
                _global(), "2026-01", Decimal("500"), _articles(),
                invoice_date=date(2026, 1, 1),
            )

        inc_mock.assert_not_called()
        assert result.invoice.invoice_number == 0


# ===================================================================
#  Drive upload failure
# ===================================================================

class TestDriveUploadFailure:

    def test_drive_failure_does_not_crash(self):
        docs = MagicMock()
        drive = MagicMock()
        _setup_docs(docs)
        drive.get_contractor_folder.return_value = "folder1"
        drive.upload_invoice_pdf.side_effect = RuntimeError("Drive down")
        gen = _make_gen(docs, drive)

        with patch(_PATCH_SAVE):
            result = gen.create_and_save(
                _global(), "2026-01", Decimal("500"), _articles(),
                invoice_date=date(2026, 1, 1),
            )

        assert result.invoice.gdrive_path == ""
        assert result.pdf_bytes == b"%PDF-fake"


# ===================================================================
#  Invoice date defaults
# ===================================================================

class TestInvoiceDateDefault:

    def test_date_defaults_to_today(self):
        docs = MagicMock()
        drive = MagicMock()
        _setup_docs(docs)
        drive.get_contractor_folder.return_value = "folder1"
        drive.upload_invoice_pdf.return_value = ""
        gen = _make_gen(docs, drive)

        with patch(_PATCH_SAVE):
            result = gen.create_and_save(
                _global(), "2026-01", Decimal("100"), _articles(),
            )

        # The invoice_date used in replacements should be today
        replacements = docs.replace_text.call_args[0][1]
        today = date.today()
        assert replacements["{{INVOICE_DATE}}"] == today.strftime("%d.%m.%Y")


# ===================================================================
#  Article IDs stored in invoice model
# ===================================================================

class TestArticleIdsInInvoice:

    def test_article_ids_populated(self):
        docs = MagicMock()
        drive = MagicMock()
        _setup_docs(docs)
        drive.get_contractor_folder.return_value = "folder1"
        drive.upload_invoice_pdf.return_value = ""
        gen = _make_gen(docs, drive)

        articles = [ArticleEntry(article_id="a1"), ArticleEntry(article_id="a2"), ArticleEntry(article_id="a3")]
        with patch(_PATCH_SAVE):
            result = gen.create_and_save(
                _global(), "2026-01", Decimal("300"), articles,
                invoice_date=date(2026, 1, 1),
            )

        assert result.invoice.article_ids == ["a1", "a2", "a3"]

    def test_empty_articles(self):
        docs = MagicMock()
        drive = MagicMock()
        _setup_docs(docs)
        drive.get_contractor_folder.return_value = "folder1"
        drive.upload_invoice_pdf.return_value = ""
        gen = _make_gen(docs, drive)

        with patch(_PATCH_SAVE):
            result = gen.create_and_save(
                _global(), "2026-01", Decimal("100"), [],
                invoice_date=date(2026, 1, 1),
            )

        assert result.invoice.article_ids == []


# ===================================================================
#  Invoice status is always DRAFT
# ===================================================================

class TestInvoiceStatus:

    def test_status_is_draft(self):
        docs = MagicMock()
        drive = MagicMock()
        _setup_docs(docs)
        drive.get_contractor_folder.return_value = "folder1"
        drive.upload_invoice_pdf.return_value = ""
        gen = _make_gen(docs, drive)

        with patch(_PATCH_SAVE):
            result = gen.create_and_save(
                _global(), "2026-01", Decimal("100"), _articles(),
                invoice_date=date(2026, 1, 1),
            )

        assert result.invoice.status == InvoiceStatus.DRAFT
