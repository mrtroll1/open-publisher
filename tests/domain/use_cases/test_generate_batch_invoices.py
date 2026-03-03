from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from backend.domain.use_cases.generate_batch_invoices import BatchResult, GenerateBatchInvoices
from backend.domain.use_cases.generate_invoice import InvoiceResult
from common.models import (
    ArticleEntry,
    Currency,
    GlobalContractor,
    IPContractor,
    Invoice,
    InvoiceStatus,
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


def _invoice(contractor_id: str = "g1", **overrides) -> Invoice:
    kwargs = dict(
        contractor_id=contractor_id, contractor_name="Test",
        invoice_number=1, month="2026-01",
        amount=Decimal("500"), currency=Currency.EUR,
    )
    kwargs.update(overrides)
    return Invoice(**kwargs)


# ---------------------------------------------------------------------------
#  Patch paths
# ---------------------------------------------------------------------------

_PATCH_LOAD = "backend.domain.use_cases.generate_batch_invoices.load_invoices"
_PATCH_BUDGET = "backend.domain.use_cases.generate_batch_invoices.read_all_amounts"
_PATCH_REPUBLIC = "backend.domain.use_cases.generate_batch_invoices.RepublicGateway"
_PATCH_GEN = "backend.domain.use_cases.generate_batch_invoices.GenerateInvoice"


def _make_batch(mock_republic, mock_gen) -> GenerateBatchInvoices:
    batch = GenerateBatchInvoices.__new__(GenerateBatchInvoices)
    batch._content = mock_republic
    batch._gen = mock_gen
    return batch


def _inv_result(contractor_id="g1", amount=500) -> InvoiceResult:
    return InvoiceResult(
        pdf_bytes=b"%PDF",
        invoice=_invoice(contractor_id=contractor_id, amount=Decimal(str(amount))),
    )


# ===================================================================
#  Filtering logic
# ===================================================================

class TestBatchFiltering:

    def test_skips_already_generated(self):
        republic = MagicMock()
        gen = MagicMock()
        batch = _make_batch(republic, gen)

        existing = [_invoice(contractor_id="g1")]
        budget = {"test global": (500, 0, "")}

        with patch(_PATCH_LOAD, return_value=existing), \
             patch(_PATCH_BUDGET, return_value=budget):
            result = batch.execute([_global()], "2026-01")

        assert result.total == 0
        gen.create_and_save.assert_not_called()

    def test_skips_contractors_without_budget(self):
        republic = MagicMock()
        gen = MagicMock()
        batch = _make_batch(republic, gen)

        # Budget has an entry for a different name
        budget = {"other person": (500, 0, "")}

        with patch(_PATCH_LOAD, return_value=[]), \
             patch(_PATCH_BUDGET, return_value=budget):
            result = batch.execute([_global()], "2026-01")

        assert result.total == 0
        gen.create_and_save.assert_not_called()

    def test_skips_zero_amount(self):
        republic = MagicMock()
        gen = MagicMock()
        batch = _make_batch(republic, gen)

        # EUR amount = 0, RUB amount = 0
        budget = {"test global": (0, 0, "")}

        with patch(_PATCH_LOAD, return_value=[]), \
             patch(_PATCH_BUDGET, return_value=budget):
            result = batch.execute([_global()], "2026-01")

        assert result.total == 0

    def test_uses_eur_for_global_rub_for_samoz(self):
        republic = MagicMock()
        republic.fetch_articles.return_value = []
        gen = MagicMock()
        gen.create_and_save.return_value = _inv_result()
        batch = _make_batch(republic, gen)

        g = _global(id="g1", name_en="Author One")
        s = _samoz(id="s1", name_ru="Автор Два")

        # budget: eur=300, rub=15000
        budget = {
            "author one": (300, 0, ""),
            "автор два": (0, 15000, ""),
        }

        with patch(_PATCH_LOAD, return_value=[]), \
             patch(_PATCH_BUDGET, return_value=budget):
            result = batch.execute([g, s], "2026-01")

        assert result.total == 2
        calls = gen.create_and_save.call_args_list
        # First call: global contractor with EUR amount 300
        assert calls[0][0][2] == Decimal("300")
        # Second call: samoz contractor with RUB amount 15000
        assert calls[1][0][2] == Decimal("15000")

    def test_empty_budget_raises(self):
        republic = MagicMock()
        gen = MagicMock()
        batch = _make_batch(republic, gen)

        with patch(_PATCH_LOAD, return_value=[]), \
             patch(_PATCH_BUDGET, return_value={}):
            with pytest.raises(ValueError, match="Бюджетная таблица"):
                batch.execute([_global()], "2026-01")


# ===================================================================
#  Success paths and counting
# ===================================================================

class TestBatchSuccess:

    def test_generates_and_counts_by_type(self):
        republic = MagicMock()
        republic.fetch_articles.return_value = [ArticleEntry(article_id="a1")]
        gen = MagicMock()
        gen.create_and_save.return_value = _inv_result()
        batch = _make_batch(republic, gen)

        g = _global(id="g1", name_en="Global One")
        s = _samoz(id="s1", name_ru="Самоз Один")
        ip = _ip(id="ip1", name_ru="ИП Один")

        budget = {
            "global one": (500, 0, ""),
            "самоз один": (0, 10000, ""),
            "ип один": (0, 12000, ""),
        }

        with patch(_PATCH_LOAD, return_value=[]), \
             patch(_PATCH_BUDGET, return_value=budget):
            result = batch.execute([g, s, ip], "2026-01")

        assert result.total == 3
        assert result.counts["global"] == 1
        assert result.counts["samozanyaty"] == 1
        assert result.counts["ip"] == 1
        assert len(result.generated) == 3
        assert len(result.errors) == 0

    def test_empty_contractors_list(self):
        republic = MagicMock()
        gen = MagicMock()
        batch = _make_batch(republic, gen)

        budget = {"someone": (100, 0, "")}

        with patch(_PATCH_LOAD, return_value=[]), \
             patch(_PATCH_BUDGET, return_value=budget):
            result = batch.execute([], "2026-01")

        assert result.total == 0
        assert len(result.generated) == 0
        gen.create_and_save.assert_not_called()

    def test_generated_tuple_contains_pdf_contractor_invoice(self):
        republic = MagicMock()
        republic.fetch_articles.return_value = []
        gen = MagicMock()
        inv_result = _inv_result()
        gen.create_and_save.return_value = inv_result
        batch = _make_batch(republic, gen)

        g = _global(id="g1", name_en="Test Global")
        budget = {"test global": (500, 0, "")}

        with patch(_PATCH_LOAD, return_value=[]), \
             patch(_PATCH_BUDGET, return_value=budget):
            result = batch.execute([g], "2026-01")

        pdf, contractor, invoice = result.generated[0]
        assert pdf == b"%PDF"
        assert contractor.id == "g1"
        assert isinstance(invoice, Invoice)


# ===================================================================
#  Error handling
# ===================================================================

class TestBatchErrors:

    def test_article_fetch_error_logged_and_continues(self):
        republic = MagicMock()
        republic.fetch_articles.side_effect = [
            RuntimeError("API fail"),
            [ArticleEntry(article_id="a1")],
        ]
        gen = MagicMock()
        gen.create_and_save.return_value = _inv_result(contractor_id="s1")
        batch = _make_batch(republic, gen)

        g = _global(id="g1", name_en="Author A")
        s = _samoz(id="s1", name_ru="Автор Б")
        budget = {
            "author a": (300, 0, ""),
            "автор б": (0, 10000, ""),
        }

        with patch(_PATCH_LOAD, return_value=[]), \
             patch(_PATCH_BUDGET, return_value=budget):
            result = batch.execute([g, s], "2026-01")

        assert len(result.errors) == 1
        assert "Author A" in result.errors[0]
        assert "API" in result.errors[0]
        assert len(result.generated) == 1

    def test_generate_error_logged_and_continues(self):
        republic = MagicMock()
        republic.fetch_articles.return_value = []
        gen = MagicMock()
        gen.create_and_save.side_effect = [
            RuntimeError("Doc generation fail"),
            _inv_result(contractor_id="s1"),
        ]
        batch = _make_batch(republic, gen)

        g = _global(id="g1", name_en="Author A")
        s = _samoz(id="s1", name_ru="Автор Б")
        budget = {
            "author a": (300, 0, ""),
            "автор б": (0, 10000, ""),
        }

        with patch(_PATCH_LOAD, return_value=[]), \
             patch(_PATCH_BUDGET, return_value=budget):
            result = batch.execute([g, s], "2026-01")

        assert len(result.errors) == 1
        assert "Author A" in result.errors[0]
        assert "генерации" in result.errors[0]
        assert len(result.generated) == 1


# ===================================================================
#  Progress callback
# ===================================================================

class TestBatchProgress:

    def test_progress_called_for_each_contractor(self):
        republic = MagicMock()
        republic.fetch_articles.return_value = []
        gen = MagicMock()
        gen.create_and_save.return_value = _inv_result()
        batch = _make_batch(republic, gen)

        g1 = _global(id="g1", name_en="Author A")
        g2 = _global(id="g2", name_en="Author B")
        budget = {
            "author a": (300, 0, ""),
            "author b": (400, 0, ""),
        }

        progress = MagicMock()

        with patch(_PATCH_LOAD, return_value=[]), \
             patch(_PATCH_BUDGET, return_value=budget):
            result = batch.execute([g1, g2], "2026-01", on_progress=progress)

        assert progress.call_count == 2
        progress.assert_any_call(1, 2)
        progress.assert_any_call(2, 2)

    def test_progress_called_on_error(self):
        republic = MagicMock()
        republic.fetch_articles.side_effect = RuntimeError("fail")
        gen = MagicMock()
        batch = _make_batch(republic, gen)

        g = _global(id="g1", name_en="Author A")
        budget = {"author a": (300, 0, "")}
        progress = MagicMock()

        with patch(_PATCH_LOAD, return_value=[]), \
             patch(_PATCH_BUDGET, return_value=budget):
            batch.execute([g], "2026-01", on_progress=progress)

        progress.assert_called_once_with(1, 1)

    def test_no_progress_callback_is_fine(self):
        republic = MagicMock()
        republic.fetch_articles.return_value = []
        gen = MagicMock()
        gen.create_and_save.return_value = _inv_result()
        batch = _make_batch(republic, gen)

        g = _global(id="g1", name_en="Author A")
        budget = {"author a": (300, 0, "")}

        with patch(_PATCH_LOAD, return_value=[]), \
             patch(_PATCH_BUDGET, return_value=budget):
            result = batch.execute([g], "2026-01")

        assert result.total == 1


# ===================================================================
#  Debug mode passthrough
# ===================================================================

class TestBatchDebugMode:

    def test_debug_flag_passed_to_generate(self):
        republic = MagicMock()
        republic.fetch_articles.return_value = []
        gen = MagicMock()
        gen.create_and_save.return_value = _inv_result()
        batch = _make_batch(republic, gen)

        g = _global(id="g1", name_en="Author A")
        budget = {"author a": (300, 0, "")}

        with patch(_PATCH_LOAD, return_value=[]), \
             patch(_PATCH_BUDGET, return_value=budget):
            batch.execute([g], "2026-01", debug=True)

        _, kwargs = gen.create_and_save.call_args
        assert kwargs.get("debug") is True
