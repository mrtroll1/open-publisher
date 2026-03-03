import pytest
from decimal import Decimal
from unittest.mock import patch

from backend.domain.use_cases.parse_bank_statement import (
    _bo,
    _categorize_transactions,
    _classify_person,
    _is_owner,
    _match_service,
    _month_label,
    _to_rub,
)
from common.models import AirtableExpense


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


# ===================================================================
#  _categorize_transactions — the core categorization engine
# ===================================================================

# Module path prefix for patching config values used inside parse_bank_statement
_MOD = "backend.domain.use_cases.parse_bank_statement"

# Fixed test config values
_TEST_OWNER_NAME = "Test Owner"
_TEST_OWNER_KEYWORDS = ["OwnerKW"]
_TEST_UNIT_PRIMARY = "primary"
_TEST_UNIT_SECONDARY = "secondary"
_TEST_DEFAULT_ENTITY = "test-entity"
_TEST_KNOWN_PEOPLE = {
    "Alice Smith": {"group": "editors", "parent": "staff", "unit": "primary", "desc": "Editing"},
}
_TEST_SERVICE_MAP = {
    "TestService": {
        "contractor": "Test Service Inc.",
        "description": "Test subscription",
        "group": "infrastructure",
        "parent": "goods and services",
        "unit": "backoffice primary",
    },
    "SplitService": {
        "contractor": "Split Corp.",
        "description": "Shared tool",
        "group": "tools",
        "parent": "goods and services",
        "unit": "backoffice primary",
        "split": True,
    },
}

# Rate used in all tests: 1 AED = 25 RUB
_RATE = 25.0


def _patch_config():
    """Return a combined decorator that patches all config values."""
    return [
        patch(f"{_MOD}.OWNER_NAME", _TEST_OWNER_NAME),
        patch(f"{_MOD}.OWNER_KEYWORDS", _TEST_OWNER_KEYWORDS),
        patch(f"{_MOD}.UNIT_PRIMARY", _TEST_UNIT_PRIMARY),
        patch(f"{_MOD}.UNIT_SECONDARY", _TEST_UNIT_SECONDARY),
        patch(f"{_MOD}.DEFAULT_ENTITY", _TEST_DEFAULT_ENTITY),
        patch(f"{_MOD}.KNOWN_PEOPLE", _TEST_KNOWN_PEOPLE),
        patch(f"{_MOD}.SERVICE_MAP", _TEST_SERVICE_MAP),
    ]


def _apply_patches(func):
    """Apply all config patches as nested decorators."""
    for p in reversed(_patch_config()):
        func = p(func)
    return func


def _row(txn_type="", description="", amount="0", date="2025-01-15"):
    """Helper to build a CSV row dict."""
    return {
        "Transaction type": txn_type,
        "Description": description,
        "Amount": amount,
        "Date": date,
    }


class TestCategorizeIncomeSkip:
    """Positive transfers from NETWORK INTERNATIONAL (Stripe payouts) are skipped."""

    @_apply_patches
    def test_stripe_payout_skipped(self):
        rows = [_row("Transfers", "From NETWORK INTERNATIONAL LLC", "5000")]
        result = _categorize_transactions(rows, _RATE)
        assert result == []

    @_apply_patches
    def test_stripe_payout_case_insensitive_network(self):
        rows = [_row("Transfers", "From Network International Company", "1000")]
        result = _categorize_transactions(rows, _RATE)
        assert result == []


class TestCategorizeOwnerTransfer:
    """Positive transfers matching OWNER_KEYWORDS create owner expense."""

    @_apply_patches
    def test_owner_incoming_creates_expense(self):
        rows = [_row("Transfers", "From Mr OwnerKW Person", "2000", "2025-02-10")]
        result = _categorize_transactions(rows, _RATE)
        assert len(result) == 1
        e = result[0]
        assert e.contractor == _TEST_OWNER_NAME
        assert e.payed == "2025-02-10"
        assert e.amount_rub == 2000 * _RATE
        assert e.unit == "backoffice primary"
        assert e.entity == _TEST_DEFAULT_ENTITY
        assert e.description == "Зп + амазон + авторы"
        assert e.group == "managers"
        assert e.parent == "staff"

    @_apply_patches
    def test_owner_keyword_not_matching(self):
        rows = [_row("Transfers", "From Random Person", "500")]
        result = _categorize_transactions(rows, _RATE)
        assert result == []


class TestCategorizeOtherPositiveTransfers:
    """Positive transfers that aren't Stripe or owner are skipped."""

    @_apply_patches
    def test_positive_transfer_unknown_sender_skipped(self):
        rows = [_row("Transfers", "From Some Company", "3000")]
        result = _categorize_transactions(rows, _RATE)
        assert result == []

    @_apply_patches
    def test_positive_transfer_no_from_pattern_skipped(self):
        # Description doesn't match "From <Name>" pattern — falls through without match
        rows = [_row("Transfers", "Incoming wire", "1000")]
        result = _categorize_transactions(rows, _RATE)
        assert result == []


class TestCategorizeFeesSwift:
    """SWIFT fees are collected and aggregated at the end."""

    @_apply_patches
    def test_single_swift_fee(self):
        rows = [_row("Fees", "Swift transfer fee", "-15", "2025-03-01")]
        result = _categorize_transactions(rows, _RATE)
        assert len(result) == 1
        e = result[0]
        assert e.contractor == "Wio Bank"
        assert e.amount_rub == 15 * _RATE
        assert e.group == "comissions"
        assert e.parent == "expenses"
        assert e.unit == "backoffice primary"
        assert "SWIFT" in e.description
        assert "March 2025" in e.description

    @_apply_patches
    def test_swift_uppercase_in_description(self):
        rows = [_row("Fees", "SWIFT outgoing fee", "-20", "2025-06-15")]
        result = _categorize_transactions(rows, _RATE)
        assert len(result) == 1
        assert result[0].amount_rub == 20 * _RATE


class TestCategorizeFeesFx:
    """Foreign exchange fees are collected and aggregated as 50/50 split."""

    @_apply_patches
    def test_single_fx_fee_creates_two_expenses(self):
        rows = [_row("Fees", "Foreign exchange markup", "-10", "2025-04-20")]
        result = _categorize_transactions(rows, _RATE)
        assert len(result) == 2
        # First is secondary unit, second is primary
        assert result[0].unit == "backoffice secondary"
        assert result[1].unit == "backoffice primary"
        # Each gets half
        assert result[0].amount_rub == 5 * _RATE
        assert result[1].amount_rub == 5 * _RATE
        assert result[0].splited == "checked"
        assert result[1].splited == "checked"
        assert result[0].group == "comissions"
        assert "Foreign exchange" in result[0].description


class TestCategorizeFeesSubscription:
    """Subscription fees create a single Wio Bank expense."""

    @_apply_patches
    def test_subscription_fee(self):
        rows = [_row("Fees", "Subscription fee - monthly", "-25", "2025-05-01")]
        result = _categorize_transactions(rows, _RATE)
        assert len(result) == 1
        e = result[0]
        assert e.contractor == "Wio Bank"
        assert e.amount_rub == 25 * _RATE
        # unit = DEFAULT_ENTITY.split("-")[0] → "test"
        assert e.unit == "test"
        assert e.entity == _TEST_DEFAULT_ENTITY
        assert e.description == "Subscription fee - monthly"
        assert e.group == "banking"
        assert e.parent == "goods and services"


class TestCategorizeFeesUnknown:
    """Unknown fee types are skipped."""

    @_apply_patches
    def test_unknown_fee_skipped(self):
        rows = [_row("Fees", "Some random fee", "-5")]
        result = _categorize_transactions(rows, _RATE)
        assert result == []


class TestCategorizeOutgoingTransfers:
    """Outgoing transfers (To <Name>) classify via _classify_person."""

    @_apply_patches
    def test_known_person_transfer(self):
        rows = [_row("Transfers", "To Alice Smith", "-1000", "2025-01-20")]
        result = _categorize_transactions(rows, _RATE)
        assert len(result) == 1
        e = result[0]
        assert e.contractor == "Alice Smith"
        assert e.amount_rub == 1000 * _RATE
        assert e.group == "editors"
        assert e.parent == "staff"
        assert e.unit == "primary"
        assert e.description == "Editing"
        assert e.entity == _TEST_DEFAULT_ENTITY
        assert e.payed == "2025-01-20"

    @_apply_patches
    def test_unknown_person_gets_defaults(self):
        rows = [_row("Transfers", "To Unknown Writer", "-500", "2025-02-15")]
        result = _categorize_transactions(rows, _RATE)
        assert len(result) == 1
        e = result[0]
        assert e.contractor == "Unknown Writer"
        assert e.group == "authors"
        assert e.parent == "staff"
        assert e.unit == _TEST_UNIT_PRIMARY
        assert e.description == "Гонорар автора"

    @_apply_patches
    def test_outgoing_transfer_no_to_pattern(self):
        # Description doesn't match "To <Name>" — no expense
        rows = [_row("Transfers", "Wire outgoing", "-200")]
        result = _categorize_transactions(rows, _RATE)
        assert result == []


class TestCategorizeCardKnownServiceNoSplit:
    """Card payments matching SERVICE_MAP without split create 1 expense."""

    @_apply_patches
    def test_known_service_single_expense(self):
        rows = [_row("Card", "Payment TestService monthly", "-100", "2025-03-10")]
        result = _categorize_transactions(rows, _RATE)
        assert len(result) == 1
        e = result[0]
        assert e.contractor == "Test Service Inc."
        assert e.amount_rub == 100 * _RATE
        assert e.unit == "backoffice primary"
        assert e.description == "Test subscription"
        assert e.group == "infrastructure"
        assert e.parent == "goods and services"
        assert e.splited == ""
        assert e.comment == ""


class TestCategorizeCardKnownServiceSplit:
    """Card payments matching SERVICE_MAP with split=True create 2 expenses (50/50)."""

    @_apply_patches
    def test_split_service_creates_two(self):
        rows = [_row("Card", "SplitService payment", "-200", "2025-04-05")]
        result = _categorize_transactions(rows, _RATE)
        assert len(result) == 2
        # First: secondary, second: primary
        assert result[0].unit == "backoffice secondary"
        assert result[1].unit == "backoffice primary"
        # Each gets half the amount
        assert result[0].amount_rub == 100 * _RATE
        assert result[1].amount_rub == 100 * _RATE
        assert result[0].contractor == "Split Corp."
        assert result[1].contractor == "Split Corp."
        assert result[0].splited == "checked"
        assert result[1].splited == "checked"
        assert result[0].description == "Shared tool"
        assert result[0].group == "tools"


class TestCategorizeCardUnknownService:
    """Card payments with no SERVICE_MAP match create 2 expenses with NEEDS REVIEW."""

    @_apply_patches
    def test_unknown_service_creates_two_with_review(self):
        rows = [_row("Card", "Random Vendor XYZ", "-80", "2025-05-20")]
        result = _categorize_transactions(rows, _RATE)
        assert len(result) == 2
        for e in result:
            assert e.contractor == "Random Vendor XYZ"
            assert e.amount_rub == 40 * _RATE
            assert e.splited == "checked"
            assert e.comment == "NEEDS REVIEW"
            assert e.group == "infrastructure"
            assert e.parent == "goods and services"
            assert "Оплата картой:" in e.description
        assert result[0].unit == "backoffice secondary"
        assert result[1].unit == "backoffice primary"


class TestCategorizeInvalidAmount:
    """Rows with non-numeric Amount are silently skipped."""

    @_apply_patches
    def test_non_numeric_amount_skipped(self):
        rows = [_row("Transfers", "To Alice Smith", "not-a-number")]
        result = _categorize_transactions(rows, _RATE)
        assert result == []

    @_apply_patches
    def test_empty_amount_skipped(self):
        rows = [_row("Transfers", "To Alice Smith", "")]
        result = _categorize_transactions(rows, _RATE)
        assert result == []


class TestCategorizeEmptyRows:
    """Various malformed/empty rows are handled gracefully."""

    @_apply_patches
    def test_completely_empty_row(self):
        rows = [{}]
        result = _categorize_transactions(rows, _RATE)
        assert result == []

    @_apply_patches
    def test_row_missing_transaction_type(self):
        rows = [{"Description": "Something", "Amount": "-50", "Date": "2025-01-01"}]
        result = _categorize_transactions(rows, _RATE)
        assert result == []

    @_apply_patches
    def test_row_with_zero_amount(self):
        rows = [_row("Transfers", "From Someone", "0")]
        result = _categorize_transactions(rows, _RATE)
        assert result == []

    @_apply_patches
    def test_unknown_transaction_type(self):
        rows = [_row("Refund", "Some refund", "-100")]
        result = _categorize_transactions(rows, _RATE)
        assert result == []


class TestCategorizeMixedScenario:
    """Multiple rows of different types in one call produce correct results."""

    @_apply_patches
    def test_mixed_rows(self):
        rows = [
            # 1. Stripe payout — skipped
            _row("Transfers", "From NETWORK INTERNATIONAL LLC", "5000", "2025-01-01"),
            # 2. Owner transfer — 1 expense
            _row("Transfers", "From OwnerKW Ltd", "2000", "2025-01-02"),
            # 3. SWIFT fee — collected
            _row("Fees", "Swift transfer fee", "-15", "2025-01-03"),
            # 4. Outgoing transfer — 1 expense
            _row("Transfers", "To Alice Smith", "-1000", "2025-01-04"),
            # 5. Known card service (no split) — 1 expense
            _row("Card", "TestService renewal", "-100", "2025-01-05"),
            # 6. Unknown card — 2 expenses
            _row("Card", "Mystery Vendor", "-60", "2025-01-06"),
            # 7. Invalid amount — skipped
            _row("Card", "Something", "abc", "2025-01-07"),
        ]
        result = _categorize_transactions(rows, _RATE)

        # Expected: owner(1) + Alice(1) + TestService(1) + Mystery(2) + SWIFT agg(1) = 6
        assert len(result) == 6

        # Owner expense
        owner = [e for e in result if e.contractor == _TEST_OWNER_NAME]
        assert len(owner) == 1
        assert owner[0].amount_rub == 2000 * _RATE

        # Alice expense
        alice = [e for e in result if e.contractor == "Alice Smith"]
        assert len(alice) == 1
        assert alice[0].group == "editors"

        # TestService expense
        ts = [e for e in result if e.contractor == "Test Service Inc."]
        assert len(ts) == 1

        # Mystery Vendor (2 split expenses)
        mystery = [e for e in result if e.contractor == "Mystery Vendor"]
        assert len(mystery) == 2
        assert all(e.comment == "NEEDS REVIEW" for e in mystery)

        # SWIFT fee aggregated
        swift = [e for e in result if "SWIFT" in e.description]
        assert len(swift) == 1
        assert swift[0].amount_rub == 15 * _RATE


class TestCategorizeSwiftAggregation:
    """Multiple SWIFT fee rows aggregate into 1 expense with sum and latest date."""

    @_apply_patches
    def test_multiple_swift_fees_aggregated(self):
        rows = [
            _row("Fees", "Swift transfer fee", "-10", "2025-06-01"),
            _row("Fees", "Swift outgoing charge", "-20", "2025-06-15"),
            _row("Fees", "SWIFT international", "-5", "2025-06-10"),
        ]
        result = _categorize_transactions(rows, _RATE)
        assert len(result) == 1
        e = result[0]
        assert e.contractor == "Wio Bank"
        # Total: 10 + 20 + 5 = 35
        assert e.amount_rub == 35 * _RATE
        # Latest date
        assert e.payed == "2025-06-15"
        assert "SWIFT" in e.description
        assert "June 2025" in e.description
        assert e.unit == "backoffice primary"
        assert e.group == "comissions"
        assert e.parent == "expenses"


class TestCategorizeFxAggregation:
    """Multiple FX fee rows aggregate into 2 split expenses (50/50)."""

    @_apply_patches
    def test_multiple_fx_fees_aggregated_and_split(self):
        rows = [
            _row("Fees", "Foreign exchange markup", "-8", "2025-07-01"),
            _row("Fees", "Foreign exchange fee", "-12", "2025-07-20"),
        ]
        result = _categorize_transactions(rows, _RATE)
        assert len(result) == 2
        # Total: 8 + 12 = 20 → half = 10 each
        assert result[0].amount_rub == 10 * _RATE
        assert result[1].amount_rub == 10 * _RATE
        assert result[0].unit == "backoffice secondary"
        assert result[1].unit == "backoffice primary"
        # Latest date
        assert result[0].payed == "2025-07-20"
        assert result[1].payed == "2025-07-20"
        assert result[0].splited == "checked"
        assert "Foreign exchange" in result[0].description
        assert "July 2025" in result[0].description
        assert result[0].contractor == "Wio Bank"
        assert result[0].group == "comissions"
        assert result[0].parent == "expenses"


class TestCategorizeEdgeCases:
    """Additional edge cases for completeness."""

    @_apply_patches
    def test_empty_rows_list(self):
        result = _categorize_transactions([], _RATE)
        assert result == []

    @_apply_patches
    def test_positive_card_payment_ignored(self):
        # Card with positive amount — doesn't match "Card and amount < 0" branch
        rows = [_row("Card", "Refund TestService", "50")]
        result = _categorize_transactions(rows, _RATE)
        assert result == []

    @_apply_patches
    def test_whitespace_in_fields(self):
        rows = [{"Transaction type": " Transfers ", "Description": " To Alice Smith ",
                 "Amount": " -500 ", "Date": " 2025-01-01 "}]
        result = _categorize_transactions(rows, _RATE)
        assert len(result) == 1
        assert result[0].contractor == "Alice Smith"

    @_apply_patches
    def test_subscription_fee_entity_split(self):
        """Unit is derived from DEFAULT_ENTITY.split('-')[0]."""
        rows = [_row("Fees", "Subscription fee", "-30")]
        result = _categorize_transactions(rows, _RATE)
        assert len(result) == 1
        # "test-entity".split("-")[0] = "test"
        assert result[0].unit == "test"

    @_apply_patches
    def test_negative_fee_absolute_value_used(self):
        """Fees use abs(amount) for conversion."""
        rows = [_row("Fees", "Subscription fee", "-42", "2025-08-01")]
        result = _categorize_transactions(rows, _RATE)
        assert result[0].amount_rub == 42 * _RATE

    @_apply_patches
    def test_outgoing_transfer_uses_absolute_value(self):
        """Outgoing transfers use abs(amount) for RUB conversion."""
        rows = [_row("Transfers", "To Alice Smith", "-300")]
        result = _categorize_transactions(rows, _RATE)
        assert result[0].amount_rub == 300 * _RATE
