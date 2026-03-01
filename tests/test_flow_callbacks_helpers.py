"""Tests for pure helper functions in telegram_bot/flow_callbacks.py."""

import pytest

from common.models import (
    GlobalContractor,
    IPContractor,
    RoleCode,
    SamozanyatyContractor,
)
from telegram_bot.flow_callbacks import _dup_button_label


# ---------------------------------------------------------------------------
#  Helpers
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
        bank_name="Банк", bank_account="12345", bik="044525225",
        corr_account="30101810400000000225",
        passport_series="1234", passport_number="567890",
        passport_issued_by="УФМС", passport_issued_date="01.01.2020",
        passport_code="123-456", ogrnip="123456789012345",
    )
    kwargs.update(overrides)
    return IPContractor(**kwargs)


# ===================================================================
#  _dup_button_label()
# ===================================================================

class TestDupButtonLabel:

    def test_no_aliases_returns_display_name(self):
        c = _global(aliases=[])
        assert _dup_button_label(c) == "Test Global"

    def test_alias_same_as_display_name(self):
        c = _global(name_en="Test Global", aliases=["Test Global"])
        assert _dup_button_label(c) == "Test Global"

    def test_alias_different_from_display_name(self):
        c = _global(name_en="Real Name", aliases=["Alias Name"])
        result = _dup_button_label(c)
        assert result == "Alias Name (Real Name)"

    def test_samozanyaty_with_alias(self):
        c = _samoz(name_ru="Иван Иванов", aliases=["Псевдоним"])
        result = _dup_button_label(c)
        assert result == "Псевдоним (Иван Иванов)"

    def test_samozanyaty_no_alias(self):
        c = _samoz(name_ru="Иван Иванов", aliases=[])
        result = _dup_button_label(c)
        assert result == "Иван Иванов"

    def test_ip_with_alias(self):
        c = _ip(name_ru="Пётр Петров", aliases=["Автор"])
        result = _dup_button_label(c)
        assert result == "Автор (Пётр Петров)"

    def test_multiple_aliases_uses_first(self):
        c = _global(name_en="Real", aliases=["First", "Second", "Third"])
        result = _dup_button_label(c)
        assert result == "First (Real)"
