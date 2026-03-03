"""Tests for budget_repo pure helpers — _sheet_name(), sheet_url()."""

import pytest

from backend.infrastructure.repositories.sheets.budget_repo import (
    SHEET_NAME_PREFIX,
    _sheet_name,
    sheet_url,
)


# ===================================================================
#  _sheet_name()
# ===================================================================

class TestSheetName:

    def test_basic_month(self):
        assert _sheet_name("2026-01") == f"{SHEET_NAME_PREFIX}2026-01"

    def test_prefix_value(self):
        assert SHEET_NAME_PREFIX == "Payments-for-"

    def test_different_months(self):
        assert _sheet_name("2025-12") == "Payments-for-2025-12"
        assert _sheet_name("2026-06") == "Payments-for-2026-06"

    def test_arbitrary_string(self):
        # The function doesn't validate, just concatenates
        assert _sheet_name("custom") == "Payments-for-custom"


# ===================================================================
#  sheet_url()
# ===================================================================

class TestSheetUrl:

    def test_basic_url(self):
        result = sheet_url("abc123")
        assert result == "https://docs.google.com/spreadsheets/d/abc123"

    def test_different_id(self):
        result = sheet_url("1A2B3C4D5E")
        assert result == "https://docs.google.com/spreadsheets/d/1A2B3C4D5E"

    def test_url_format(self):
        result = sheet_url("test-id")
        assert result.startswith("https://docs.google.com/spreadsheets/d/")
        assert result.endswith("test-id")
