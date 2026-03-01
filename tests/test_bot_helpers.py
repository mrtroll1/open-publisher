"""Tests for telegram_bot/bot_helpers.py — pure date/admin helpers."""

import pytest
from unittest.mock import patch
from datetime import date

from telegram_bot.bot_helpers import prev_month, current_month, is_admin
from common.config import ADMIN_TELEGRAM_IDS


# ===================================================================
#  prev_month()
# ===================================================================

class TestPrevMonth:

    @patch("telegram_bot.bot_helpers.date")
    def test_mid_year(self, mock_date):
        mock_date.today.return_value = date(2026, 6, 15)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        assert prev_month() == "2026-05"

    @patch("telegram_bot.bot_helpers.date")
    def test_january_wraps_to_december(self, mock_date):
        mock_date.today.return_value = date(2026, 1, 10)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        assert prev_month() == "2025-12"

    @patch("telegram_bot.bot_helpers.date")
    def test_february(self, mock_date):
        mock_date.today.return_value = date(2026, 2, 28)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        assert prev_month() == "2026-01"

    @patch("telegram_bot.bot_helpers.date")
    def test_october_pads_month(self, mock_date):
        mock_date.today.return_value = date(2026, 10, 1)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        assert prev_month() == "2026-09"

    @patch("telegram_bot.bot_helpers.date")
    def test_march_returns_02(self, mock_date):
        mock_date.today.return_value = date(2026, 3, 1)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        assert prev_month() == "2026-02"


# ===================================================================
#  current_month()
# ===================================================================

class TestCurrentMonth:

    @patch("telegram_bot.bot_helpers.date")
    def test_basic(self, mock_date):
        mock_date.today.return_value = date(2026, 3, 15)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        assert current_month() == "2026-03"

    @patch("telegram_bot.bot_helpers.date")
    def test_single_digit_month_padded(self, mock_date):
        mock_date.today.return_value = date(2026, 1, 1)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        assert current_month() == "2026-01"

    @patch("telegram_bot.bot_helpers.date")
    def test_december(self, mock_date):
        mock_date.today.return_value = date(2026, 12, 31)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        assert current_month() == "2026-12"


# ===================================================================
#  is_admin()
# ===================================================================

class TestIsAdmin:

    def test_admin_id_returns_true(self):
        if ADMIN_TELEGRAM_IDS:
            assert is_admin(ADMIN_TELEGRAM_IDS[0]) is True

    def test_non_admin_id_returns_false(self):
        assert is_admin(999999999) is False

    def test_zero_not_admin(self):
        assert is_admin(0) is False

    def test_negative_not_admin(self):
        assert is_admin(-1) is False
