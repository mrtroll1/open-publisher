import pytest

from backend.domain.compute_budget import (
    DEFAULT_RATE_EUR,
    DEFAULT_RATE_RUB,
    ComputeBudget,
    PaymentEntry,
    _compute_budget_amount,
    _role_label,
    _target_month_name,
)
from common.models import (
    Currency,
    GlobalContractor,
    RoleCode,
    SamozanyatyContractor,
)


# ---------------------------------------------------------------------------
#  Helpers to build minimal contractor objects
# ---------------------------------------------------------------------------

def _global(*, id: str = "g1", role_code: RoleCode = RoleCode.AUTHOR) -> GlobalContractor:
    return GlobalContractor(
        id=id, name_en="Test Global", address="Addr", email="a@b.c",
        bank_name="Bank", bank_account="ACC", swift="SWIFT",
        role_code=role_code,
    )


def _samoz(*, id: str = "s1", role_code: RoleCode = RoleCode.AUTHOR) -> SamozanyatyContractor:
    return SamozanyatyContractor(
        id=id, name_ru="Тест Самозанятый", address="Адрес", email="a@b.c",
        bank_name="Банк", bank_account="12345", bik="044525225",
        corr_account="30101810400000000225",
        passport_series="1234", passport_number="567890", inn="123456789012",
        role_code=role_code,
    )


# ===================================================================
#  _compute_budget_amount
# ===================================================================

class TestComputeBudgetAmount:

    def test_flat_only(self):
        assert _compute_budget_amount(500, None, 3, Currency.EUR) == 500

    def test_flat_plus_rate_plus_articles(self):
        assert _compute_budget_amount(500, 100, 3, Currency.EUR) == 500 + 100 * 3

    def test_flat_plus_rate_zero_articles(self):
        assert _compute_budget_amount(500, 100, 0, Currency.EUR) == 500

    def test_rate_only(self):
        assert _compute_budget_amount(None, 200, 5, Currency.EUR) == 200 * 5

    def test_default_eur(self):
        assert _compute_budget_amount(None, None, 4, Currency.EUR) == DEFAULT_RATE_EUR * 4

    def test_default_rub(self):
        assert _compute_budget_amount(None, None, 4, Currency.RUB) == DEFAULT_RATE_RUB * 4

    def test_default_zero_articles(self):
        assert _compute_budget_amount(None, None, 0, Currency.EUR) == 0

    def test_flat_zero_value(self):
        # flat=0 is still "not None", so returns 0
        assert _compute_budget_amount(0, None, 5, Currency.EUR) == 0

    def test_flat_zero_plus_rate(self):
        assert _compute_budget_amount(0, 50, 3, Currency.EUR) == 50 * 3


# ===================================================================
#  _target_month_name
# ===================================================================

class TestTargetMonthName:

    @pytest.mark.parametrize(
        "month, expected",
        [
            ("2026-01", "март"),
            ("2026-02", "апрель"),
            ("2026-06", "август"),
            ("2026-10", "декабрь"),
            ("2026-11", "январь"),
            ("2026-12", "февраль"),
        ],
        ids=["jan_to_mar", "feb_to_apr", "jun_to_aug",
             "oct_to_dec", "nov_wraps_to_jan", "dec_wraps_to_feb"],
    )
    def test_month_plus_two(self, month: str, expected: str) -> None:
        assert _target_month_name(month) == expected


# ===================================================================
#  _role_label
# ===================================================================

class TestRoleLabel:

    def test_redaktor(self):
        c = _global(role_code=RoleCode.REDAKTOR)
        assert _role_label(c) == "Редактор"

    def test_korrektor(self):
        c = _global(role_code=RoleCode.KORREKTOR)
        assert _role_label(c) == "Корректор"

    def test_author(self):
        c = _global(role_code=RoleCode.AUTHOR)
        assert _role_label(c) == ""

    def test_samozanyaty_redaktor(self):
        c = _samoz(role_code=RoleCode.REDAKTOR)
        assert _role_label(c) == "Редактор"


# ===================================================================
#  ComputeBudget._build_pnl_rows (static method)
# ===================================================================

class TestBuildPnlRows:

    def test_empty_pnl_data(self):
        assert ComputeBudget._build_pnl_rows({}, 90.0) == []

    def test_none_pnl_data(self):
        assert ComputeBudget._build_pnl_rows(None, 90.0) == []

    def test_zero_eur_rub_rate(self):
        data = {"revenue": 100000, "expenses": 50000, "units": ["republic"]}
        assert ComputeBudget._build_pnl_rows(data, 0) == []

    def test_revenue_and_expenses(self):
        data = {
            "month": "2026-03",
            "units": ["republic", "backoffice-republic"],
            "revenue": 123456.78,
            "expenses": 98765.43,
        }
        rows = ComputeBudget._build_pnl_rows(data, 90.0)
        assert len(rows) == 2
        assert rows[0][0] == "Revenue"
        assert "PNL (republic, backoffice-republic)" in rows[0][1]
        assert rows[0][3] == "123456.78"
        assert rows[1][0] == "Expenses"
        assert rows[1][3] == "98765.43"

    def test_zero_amount_skipped(self):
        data = {"revenue": 0, "expenses": 5000, "units": ["republic"]}
        rows = ComputeBudget._build_pnl_rows(data, 90.0)
        assert len(rows) == 1
        assert rows[0][0] == "Expenses"

    def test_units_in_category(self):
        data = {"revenue": 1000, "expenses": 0, "units": ["republic"]}
        rows = ComputeBudget._build_pnl_rows(data, 90.0)
        assert rows[0][1] == "PNL (republic)"

    def test_amount_as_string(self):
        data = {"revenue": 12345, "expenses": 0, "units": []}
        rows = ComputeBudget._build_pnl_rows(data, 90.0)
        assert rows[0][3] == "12345"


# ===================================================================
#  ComputeBudget._route_entry (static method)
# ===================================================================

class TestRouteEntry:

    def _route(self, contractor, label, entry=None, flat_ids=None):
        """Helper that routes an entry and returns the name of the list it landed in."""
        if entry is None:
            entry = PaymentEntry(name="test")
        if flat_ids is None:
            flat_ids = {}
        authors, staff, editors, services, chief = [], [], [], [], []
        ComputeBudget._route_entry(
            contractor, label, entry, flat_ids,
            authors, staff, editors, services, chief,
        )
        if services:
            return "services"
        if chief:
            return "chief"
        if editors:
            return "editors"
        if staff:
            return "staff"
        if authors:
            return "authors"
        raise AssertionError("entry was not routed anywhere")

    def test_label_foto_to_services(self):
        c = _global()
        assert self._route(c, "фото") == "services"

    def test_label_audio_to_services(self):
        c = _global()
        assert self._route(c, "аудио") == "services"

    def test_label_chief_editor(self):
        c = _global()
        assert self._route(c, "главный редактор") == "chief"

    def test_role_redaktor_to_editors(self):
        c = _global(role_code=RoleCode.REDAKTOR)
        assert self._route(c, "") == "editors"

    def test_role_korrektor_to_staff(self):
        c = _global(role_code=RoleCode.KORREKTOR)
        assert self._route(c, "") == "staff"

    def test_label_present_but_not_special_to_staff(self):
        c = _global(role_code=RoleCode.AUTHOR)
        assert self._route(c, "переводчик") == "staff"

    def test_no_label_in_flat_ids_to_staff(self):
        c = _global(id="g1", role_code=RoleCode.AUTHOR)
        assert self._route(c, "", flat_ids={"g1": (500, 0)}) == "staff"

    def test_no_label_not_in_flat_ids_to_authors(self):
        c = _global(id="g1", role_code=RoleCode.AUTHOR)
        assert self._route(c, "", flat_ids={}) == "authors"

    def test_case_insensitive_label(self):
        c = _global()
        assert self._route(c, "Фото") == "services"
        assert self._route(c, "АУДИО") == "services"
        assert self._route(c, "Главный Редактор") == "chief"

    def test_samozanyaty_author_no_label_to_authors(self):
        c = _samoz(role_code=RoleCode.AUTHOR)
        assert self._route(c, "", flat_ids={}) == "authors"
