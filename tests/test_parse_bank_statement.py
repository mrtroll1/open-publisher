import pytest
from decimal import Decimal
from unittest.mock import patch

from backend.domain.parse_bank_statement import (
    _bo,
    _classify_person,
    _is_owner,
    _match_service,
    _month_label,
    _to_rub,
)


# ===================================================================
#  _to_rub
# ===================================================================

class TestToRub:

    def test_basic_conversion(self):
        assert _to_rub(Decimal("100"), 25.0) == 2500.0

    def test_rounds_to_two_decimals(self):
        # 33.333 * 3.0 = 99.999 → rounds to 100.0
        assert _to_rub(Decimal("33.333"), 3.0) == 100.0
        assert _to_rub(Decimal("10"), 3.333) == 33.33

    def test_zero_amount(self):
        assert _to_rub(Decimal("0"), 25.0) == 0.0

    def test_zero_rate(self):
        assert _to_rub(Decimal("100"), 0) == 0.0

    def test_fractional_aed(self):
        result = _to_rub(Decimal("0.50"), 25.0)
        assert result == 12.5

    def test_large_amount(self):
        result = _to_rub(Decimal("10000"), 25.5)
        assert result == 255000.0

    @pytest.mark.parametrize(
        "aed, rate, expected",
        [
            (Decimal("1"), 1.0, 1.0),
            (Decimal("100"), 0.5, 50.0),
            (Decimal("7.77"), 10.0, 77.7),
        ],
        ids=["one_to_one", "half_rate", "fractional_aed"],
    )
    def test_parametrized(self, aed, rate, expected):
        assert _to_rub(aed, rate) == expected



# ===================================================================
#  _month_label
# ===================================================================

class TestMonthLabel:

    @pytest.mark.parametrize(
        "date_str, expected",
        [
            ("2025-01-15", "January 2025"),
            ("2025-06-01", "June 2025"),
            ("2025-12-31", "December 2025"),
            ("2024-03-10", "March 2024"),
        ],
        ids=["january", "june", "december", "march"],
    )
    def test_valid_dates(self, date_str, expected):
        assert _month_label(date_str) == expected

    def test_invalid_date_returns_input(self):
        assert _month_label("not-a-date") == "not-a-date"

    def test_empty_string_returns_input(self):
        assert _month_label("") == ""

    def test_partial_date_returns_input(self):
        assert _month_label("2025-01") == "2025-01"


# ===================================================================
#  _bo
# ===================================================================

class TestBo:

    def test_returns_backoffice_prefix(self):
        assert _bo("republic") == "backoffice republic"

    def test_with_another_unit(self):
        assert _bo("spletnik") == "backoffice spletnik"

    def test_empty_string(self):
        assert _bo("") == "backoffice "


# ===================================================================
#  _classify_person — uses KNOWN_PEOPLE from config
# ===================================================================

class TestClassifyPerson:

    def test_known_person(self):
        group, parent, unit, desc = _classify_person("Leonid Fenko")
        assert group == "developers"
        assert parent == "staff"
        assert unit == "backoffice spletnik"
        assert desc == "Разработка"

    def test_another_known_person(self):
        group, parent, unit, desc = _classify_person("Olga Kalashnikova")
        assert group == "proofreader"
        assert parent == "staff"
        assert unit == "republic"
        assert desc == "Гонорар корректора"

    def test_unknown_person_defaults(self):
        group, parent, unit, desc = _classify_person("Unknown Person")
        assert group == "authors"
        assert parent == "staff"
        assert desc == "Гонорар автора"

    def test_empty_name_defaults(self):
        group, parent, unit, desc = _classify_person("")
        assert group == "authors"
        assert parent == "staff"


# ===================================================================
#  _is_owner — uses OWNER_KEYWORDS from config
# ===================================================================

class TestIsOwner:

    def test_matches_keyword(self):
        # OWNER_KEYWORDS = ["Luka", "Asfari"]
        assert _is_owner("Luka Something") is True

    def test_matches_another_keyword(self):
        assert _is_owner("Mr Asfari") is True

    def test_no_match(self):
        assert _is_owner("John Doe") is False

    def test_empty_name(self):
        assert _is_owner("") is False

    def test_case_sensitive(self):
        # The function uses `in`, which is case-sensitive
        assert _is_owner("luka") is False
        assert _is_owner("LUKA") is False


# ===================================================================
#  _match_service — uses SERVICE_MAP from config
# ===================================================================

class TestMatchService:

    def test_exact_key_match(self):
        result = _match_service("Sinch mailgun")
        assert result is not None
        assert result["contractor"] == "Mailgun Technologies, Inc."

    def test_case_insensitive_match(self):
        result = _match_service("SINCH MAILGUN PAYMENT")
        assert result is not None
        assert result["contractor"] == "Mailgun Technologies, Inc."

    def test_key_as_substring(self):
        result = _match_service("Payment to Figma design tools")
        assert result is not None
        assert result["contractor"] == "Figma, Inc."

    def test_split_service(self):
        result = _match_service("Notion labs inc subscription")
        assert result is not None
        assert result.get("split") is True

    def test_no_match(self):
        result = _match_service("Random unknown vendor 12345")
        assert result is None

    def test_empty_description(self):
        result = _match_service("")
        assert result is None

    def test_whitespace_trimmed(self):
        result = _match_service("  Zoom com  ")
        assert result is not None
        assert result["contractor"] == "Zoom"

    def test_sentry_match(self):
        result = _match_service("Sentry subscription")
        assert result is not None
        assert result["contractor"] == "Sentry"
