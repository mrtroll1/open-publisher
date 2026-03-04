from unittest.mock import patch

import pytest

from backend.domain.use_cases.compute_budget import (
    BLANK,
    DEFAULT_RATE_EUR,
    DEFAULT_RATE_RUB,
    ComputeBudget,
    PaymentEntry,
    _compute_budget_amount,
    _pick_by_currency,
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


# ===================================================================
#  _pick_by_currency
# ===================================================================

class TestPickByCurrency:

    def test_none_input(self):
        assert _pick_by_currency(None, Currency.EUR) is None

    def test_eur_selected(self):
        assert _pick_by_currency((300, 25000), Currency.EUR) == 300

    def test_rub_selected(self):
        assert _pick_by_currency((300, 25000), Currency.RUB) == 25000

    def test_zero_treated_as_absent(self):
        assert _pick_by_currency((0, 25000), Currency.EUR) is None

    def test_both_zero(self):
        assert _pick_by_currency((0, 0), Currency.EUR) is None
        assert _pick_by_currency((0, 0), Currency.RUB) is None


# ===================================================================
#  PaymentEntry.is_blank
# ===================================================================

class TestPaymentEntryIsBlank:

    def test_entry_with_name_not_blank(self):
        e = PaymentEntry(name="Alice")
        assert not e.is_blank

    def test_blank_constant(self):
        assert BLANK.is_blank
        assert BLANK.name == ""


# ===================================================================
#  ComputeBudget._match_authors (static method)
# ===================================================================

_CONTRACTOR_REPO = "backend.domain.use_cases.compute_budget"

class TestMatchAuthors:

    def test_basic_match(self):
        c = _global(id="g1")
        contractors = [c]
        authors = [{"author": "Test Global", "post_count": 3}]
        with patch(f"{_CONTRACTOR_REPO}.find_contractor", return_value=c):
            matched, unmatched, bonuses = ComputeBudget._match_authors(
                authors, contractors, set(), {},
            )
        assert "g1" in matched
        assert matched["g1"] == (c, 3)
        assert unmatched == []
        assert bonuses == {}

    def test_unmatched_author(self):
        authors = [{"author": "Unknown Author", "post_count": 2}]
        with patch(f"{_CONTRACTOR_REPO}.find_contractor", return_value=None):
            matched, unmatched, bonuses = ComputeBudget._match_authors(
                authors, [], set(), {},
            )
        assert matched == {}
        assert unmatched == [("Unknown Author", 2)]

    def test_excluded_author_skipped(self):
        authors = [{"author": "Excluded One", "post_count": 5}]
        with patch(f"{_CONTRACTOR_REPO}.find_contractor") as mock_fc:
            matched, unmatched, bonuses = ComputeBudget._match_authors(
                authors, [], {"Excluded One"}, {},
            )
        mock_fc.assert_not_called()
        assert matched == {}
        assert unmatched == []

    def test_redirected_author(self):
        target = _global(id="g2")
        authors = [{"author": "Ghost Writer", "post_count": 4}]
        redirects = {"Ghost Writer": ("g2", True)}
        with patch(f"{_CONTRACTOR_REPO}.find_contractor_by_id", return_value=target):
            matched, unmatched, bonuses = ComputeBudget._match_authors(
                authors, [target], set(), redirects,
            )
        assert matched == {}
        assert unmatched == []
        assert "g2" in bonuses
        assert len(bonuses["g2"]) == 1
        name, amount, add = bonuses["g2"][0]
        assert name == "Ghost Writer"
        assert amount == DEFAULT_RATE_EUR * 4
        assert add is True

    def test_accumulates_counts_same_contractor(self):
        c = _global(id="g1")
        authors = [
            {"author": "Name A", "post_count": 2},
            {"author": "Name B", "post_count": 3},
        ]
        with patch(f"{_CONTRACTOR_REPO}.find_contractor", return_value=c):
            matched, unmatched, bonuses = ComputeBudget._match_authors(
                authors, [c], set(), {},
            )
        assert matched["g1"] == (c, 5)

    def test_redirect_target_not_found_falls_through(self):
        # When redirect target contractor isn't found, the author falls through
        # to normal matching (find_contractor), and ends up unmatched
        authors = [{"author": "Ghost Writer", "post_count": 1}]
        redirects = {"Ghost Writer": ("missing_id", False)}
        with patch(f"{_CONTRACTOR_REPO}.find_contractor_by_id", return_value=None), \
             patch(f"{_CONTRACTOR_REPO}.find_contractor", return_value=None):
            matched, unmatched, bonuses = ComputeBudget._match_authors(
                authors, [], set(), redirects,
            )
        assert matched == {}
        assert unmatched == [("Ghost Writer", 1)]
        assert bonuses == {}

    def test_redirect_rub_contractor(self):
        target = _samoz(id="s1")
        authors = [{"author": "RUB Writer", "post_count": 2}]
        redirects = {"RUB Writer": ("s1", False)}
        with patch(f"{_CONTRACTOR_REPO}.find_contractor_by_id", return_value=target):
            matched, unmatched, bonuses = ComputeBudget._match_authors(
                authors, [target], set(), redirects,
            )
        assert "s1" in bonuses
        name, amount, add = bonuses["s1"][0]
        assert amount == DEFAULT_RATE_RUB * 2
        assert add is False

    def test_mixed_scenario(self):
        c_matched = _global(id="g1")
        c_target = _global(id="g2")
        authors = [
            {"author": "Matched Author", "post_count": 3},
            {"author": "Excluded Author", "post_count": 1},
            {"author": "Unknown Author", "post_count": 2},
            {"author": "Redirected Author", "post_count": 4},
        ]
        excludes = {"Excluded Author"}
        redirects = {"Redirected Author": ("g2", True)}
        contractors = [c_matched, c_target]

        def mock_find(name, _contractors):
            if name == "Matched Author":
                return c_matched
            return None

        with patch(f"{_CONTRACTOR_REPO}.find_contractor", side_effect=mock_find), \
             patch(f"{_CONTRACTOR_REPO}.find_contractor_by_id", return_value=c_target):
            matched, unmatched, bonuses = ComputeBudget._match_authors(
                authors, contractors, excludes, redirects,
            )
        assert "g1" in matched
        assert matched["g1"] == (c_matched, 3)
        assert unmatched == [("Unknown Author", 2)]
        assert "g2" in bonuses


# ===================================================================
#  ComputeBudget._make_noted_entry (static method)
# ===================================================================

class TestMakeNotedEntry:

    def test_no_bonuses(self):
        c = _global(id="g1")
        entry = ComputeBudget._make_noted_entry(c, 500, "", {})
        assert entry.eur == 500
        assert entry.rub == 0
        assert entry.note == ""

    def test_bonus_add_to_total(self):
        c = _global(id="g1")
        bonuses = {"g1": [("Ghost", 200, True)]}
        entry = ComputeBudget._make_noted_entry(c, 500, "Автор", bonuses)
        assert entry.eur == 700  # 500 + 200
        assert entry.note == "Ghost (200)"

    def test_bonus_not_added_to_total(self):
        c = _global(id="g1")
        bonuses = {"g1": [("Ghost", 200, False)]}
        entry = ComputeBudget._make_noted_entry(c, 500, "", bonuses)
        assert entry.eur == 500  # bonus not added
        assert entry.note == "Ghost (200)"

    def test_rub_currency(self):
        c = _samoz(id="s1")
        entry = ComputeBudget._make_noted_entry(c, 30000, "", {})
        assert entry.rub == 30000
        assert entry.eur == 0


# ===================================================================
#  ComputeBudget._assemble_grouped_result (static method)
# ===================================================================

class TestAssembleGroupedResult:

    @staticmethod
    def _empty_groups():
        return {"authors": [], "staff": [], "editors": [], "services": [], "chief": []}

    def test_empty_groups(self):
        groups = self._empty_groups()
        result = ComputeBudget._assemble_grouped_result(groups, [])
        # services always adds a trailing blank
        assert result == [BLANK]

    def test_authors_only(self):
        groups = self._empty_groups()
        a = PaymentEntry(name="Alice", eur=100)
        groups["authors"] = [a]
        result = ComputeBudget._assemble_grouped_result(groups, [])
        # authors + 2 blanks + services blank
        assert result == [a, BLANK, BLANK, BLANK]

    def test_all_groups_populated(self):
        groups = self._empty_groups()
        a = PaymentEntry(name="Author")
        s = PaymentEntry(name="Staff")
        e = PaymentEntry(name="Editor")
        svc = PaymentEntry(name="Service")
        ch = PaymentEntry(name="Chief")
        groups["authors"] = [a]
        groups["staff"] = [s]
        groups["editors"] = [e]
        groups["services"] = [svc]
        groups["chief"] = [ch]
        result = ComputeBudget._assemble_grouped_result(groups, [])
        expected = [
            a, BLANK, BLANK,       # authors + 2 blanks
            s, BLANK,              # staff + blank
            e, BLANK,              # editors + blank
            svc, BLANK,            # services + blank
            ch, BLANK,             # chief + blank
        ]
        assert result == expected

    def test_unmatched_appended(self):
        groups = self._empty_groups()
        um = PaymentEntry(name="Unknown", eur=100)
        result = ComputeBudget._assemble_grouped_result(groups, [um])
        # services blank + unmatched
        assert result == [BLANK, um]


# ===================================================================
#  ComputeBudget._populate_sheet (instance method)
# ===================================================================

class TestPopulateSheet:

    def _make_instance(self):
        with patch(f"{_CONTRACTOR_REPO}.RepublicGateway"), \
             patch(f"{_CONTRACTOR_REPO}.RedefineGateway"):
            return ComputeBudget.__new__(ComputeBudget)

    @patch("backend.domain.use_cases.compute_budget.populate_sheet")
    def test_blank_entry_row(self, mock_pop):
        cb = self._make_instance()
        cb._populate_sheet("sheet1", [BLANK], "2026-01")
        rows = mock_pop.call_args[0][1]
        assert rows == [["", "", "", "", ""]]

    @patch("backend.domain.use_cases.compute_budget.populate_sheet")
    def test_normal_entry_row(self, mock_pop):
        cb = self._make_instance()
        entry = PaymentEntry(name="Alice", label="Редактор", eur=500, rub=0, note="hi")
        cb._populate_sheet("sheet1", [entry], "2026-01")
        rows = mock_pop.call_args[0][1]
        assert rows == [["Alice", "Редактор", "500", "", "hi"]]

    @patch("backend.domain.use_cases.compute_budget.populate_sheet")
    def test_zero_eur_rub_empty_string(self, mock_pop):
        cb = self._make_instance()
        entry = PaymentEntry(name="Bob", label="", eur=0, rub=0, note="")
        cb._populate_sheet("sheet1", [entry], "2026-01")
        rows = mock_pop.call_args[0][1]
        assert rows == [["Bob", "", "", "", ""]]
