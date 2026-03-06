import pytest

from backend.commands.invoice.resolve_amount import (
    _fmt,
    _format_budget_explanation,
    plural_ru,
    resolve_amount,
)
from common.models import GlobalContractor, RoleCode, SamozanyatyContractor


def _global(*, id="g1", name_en="Test Global", role_code=RoleCode.AUTHOR):
    return GlobalContractor(
        id=id, name_en=name_en, address="Addr", email="a@b.c",
        bank_name="Bank", bank_account="ACC", swift="SWIFT",
        role_code=role_code,
    )


def _samoz(*, id="s1", name_ru="Тест Самозанятый", role_code=RoleCode.AUTHOR):
    return SamozanyatyContractor(
        id=id, name_ru=name_ru, address="Адрес", email="a@b.c",
        bank_name="Банк", bank_account="12345", bik="044525225",
        corr_account="30101810400000000225",
        passport_series="1234", passport_number="567890", inn="123456789012",
        role_code=role_code,
    )


# ===================================================================
#  plural_ru
# ===================================================================

class TestPluralRu:

    @pytest.mark.parametrize(
        "n, expected",
        [
            (1, "1 публикация"),
            (2, "2 публикации"),
            (3, "3 публикации"),
            (4, "4 публикации"),
            (5, "5 публикаций"),
            (0, "0 публикаций"),
            (6, "6 публикаций"),
            (10, "10 публикаций"),
            (11, "11 публикаций"),
            (12, "12 публикаций"),
            (14, "14 публикаций"),
            (19, "19 публикаций"),
            (20, "20 публикаций"),
            (21, "21 публикация"),
            (22, "22 публикации"),
            (100, "100 публикаций"),
            (101, "101 публикация"),
            (111, "111 публикаций"),
        ],
        ids=[
            "1_one", "2_few", "3_few", "4_few",
            "5_many", "0_many", "6_many", "10_many",
            "11_many", "12_many", "14_many", "19_many", "20_many",
            "21_one", "22_few",
            "100_many", "101_one", "111_many",
        ],
    )
    def test_plural(self, n, expected):
        assert plural_ru(n, "публикация", "публикации", "публикаций") == expected


# ===================================================================
#  _fmt
# ===================================================================

class TestFmt:

    def test_zero(self):
        assert _fmt(0) == "0"

    def test_hundreds(self):
        assert _fmt(100) == "100"

    def test_thousands(self):
        assert _fmt(1000) == "1 000"

    def test_millions(self):
        assert _fmt(1_000_000) == "1 000 000"

    def test_negative(self):
        assert _fmt(-5000) == "-5 000"


# ===================================================================
#  _format_budget_explanation
# ===================================================================

class TestFormatBudgetExplanation:

    def test_no_note(self):
        assert _format_budget_explanation(2700, "", "€") == "Сумма: 2 700€"

    def test_none_note(self):
        assert _format_budget_explanation(2700, None, "€") == "Сумма: 2 700€"

    def test_note_with_bonuses(self):
        result = _format_budget_explanation(
            2800, "Яна Заречная (200), Иван Петров (300)", "€",
        )
        lines = result.split("\n")
        assert lines[0] == "Сумма: 2 800€"
        assert lines[1] == "2 300€ по умолчанию"
        assert lines[2] == "200€ за Яна Заречная"
        assert lines[3] == "300€ за Иван Петров"

    def test_note_invalid_format(self):
        result = _format_budget_explanation(2700, "just some text", "₽")
        assert result == "Сумма: 2 700₽"

    def test_note_one_bonus(self):
        result = _format_budget_explanation(1500, "Мария Иванова (500)", "₽")
        lines = result.split("\n")
        assert len(lines) == 3
        assert lines[0] == "Сумма: 1 500₽"
        assert lines[1] == "1 000₽ по умолчанию"
        assert lines[2] == "500₽ за Мария Иванова"

    def test_empty_parens_skipped(self):
        result = _format_budget_explanation(1000, "Name ()", "€")
        assert result == "Сумма: 1 000€"

    def test_non_numeric_in_parens_skipped(self):
        result = _format_budget_explanation(1000, "Name (abc)", "€")
        assert result == "Сумма: 1 000€"


# ===================================================================
#  resolve_amount
# ===================================================================

class TestResolveAmount:

    def test_contractor_found_eur(self):
        c = _global(name_en="Alice Smith")
        budget = {"alice smith": (500, None, "")}
        amount, explanation = resolve_amount(budget, c, 3)
        assert amount == 500
        assert "500" in explanation

    def test_contractor_found_rub(self):
        c = _samoz(name_ru="Алиса Иванова")
        budget = {"алиса иванова": (None, 15000, "")}
        amount, explanation = resolve_amount(budget, c, 2)
        assert amount == 15000

    def test_eur_contractor_only_rub_in_budget_falls_back(self):
        c = _global(name_en="Bob Jones")
        budget = {"bob jones": (None, 50000, "")}
        amount, explanation = resolve_amount(budget, c, 4)
        assert amount == 100 * 4

    def test_contractor_not_in_budget_eur(self):
        c = _global(name_en="Unknown Person")
        amount, explanation = resolve_amount({}, c, 5)
        assert amount == 100 * 5
        assert "€" in explanation

    def test_contractor_not_in_budget_rub(self):
        c = _samoz(name_ru="Неизвестный")
        amount, explanation = resolve_amount({}, c, 3)
        assert amount == 10_000 * 3
        assert "₽" in explanation

    def test_budget_entry_with_note(self):
        c = _global(name_en="Alice Smith")
        budget = {"alice smith": (800, None, "Петр Петров (300)")}
        amount, explanation = resolve_amount(budget, c, 2)
        assert amount == 800
        assert "300" in explanation
        assert "Петр Петров" in explanation

    def test_zero_articles_not_in_budget(self):
        c = _global(name_en="Nobody")
        amount, _ = resolve_amount({}, c, 0)
        assert amount == 0
