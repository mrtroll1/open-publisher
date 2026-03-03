"""Tests for Contractor subclass properties — display_name, all_names, type, currency."""

import pytest

from common.models import (
    ContractorType,
    Currency,
    GlobalContractor,
    IPContractor,
    SamozanyatyContractor,
)


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


def _samoz(**overrides) -> SamozanyatyContractor:
    kwargs = dict(
        id="s1", name_ru="Тест Самозанятый", address="Адрес", email="s@t.ru",
        bank_name="Банк", bank_account="12345", bik="044525225",
        corr_account="30101810400000000225",
        passport_series="1234", passport_number="567890", inn="123456789012",
    )
    kwargs.update(overrides)
    return SamozanyatyContractor(**kwargs)


# ===================================================================
#  display_name
# ===================================================================

class TestDisplayName:

    def test_global_uses_name_en(self):
        c = _global(name_en="John Smith")
        assert c.display_name == "John Smith"

    def test_global_fallback_to_id(self):
        c = _global(name_en="")
        assert c.display_name == "g1"

    def test_ip_uses_name_ru(self):
        c = _ip(name_ru="Иван Иванов")
        assert c.display_name == "Иван Иванов"

    def test_ip_fallback_to_id(self):
        c = _ip(name_ru="")
        assert c.display_name == "ip1"

    def test_samoz_uses_name_ru(self):
        c = _samoz(name_ru="Пётр Петров")
        assert c.display_name == "Пётр Петров"

    def test_samoz_fallback_to_id(self):
        c = _samoz(name_ru="")
        assert c.display_name == "s1"


# ===================================================================
#  all_names
# ===================================================================

class TestAllNames:

    def test_global_includes_name_en(self):
        c = _global(name_en="Jane Doe", aliases=[])
        assert "Jane Doe" in c.all_names

    def test_global_includes_aliases(self):
        c = _global(aliases=["Alias1", "Alias2"])
        assert "Alias1" in c.all_names
        assert "Alias2" in c.all_names

    def test_global_name_first_then_aliases(self):
        c = _global(name_en="Real", aliases=["A1", "A2"])
        assert c.all_names == ["Real", "A1", "A2"]

    def test_global_empty_name_not_included(self):
        c = _global(name_en="", aliases=["Only Alias"])
        assert c.all_names == ["Only Alias"]

    def test_ip_includes_name_ru(self):
        c = _ip(name_ru="Иван", aliases=[])
        assert "Иван" in c.all_names

    def test_ip_empty_name_not_included(self):
        c = _ip(name_ru="", aliases=["Alias"])
        assert c.all_names == ["Alias"]

    def test_samoz_includes_name_ru(self):
        c = _samoz(name_ru="Пётр", aliases=["Псевдоним"])
        assert c.all_names == ["Пётр", "Псевдоним"]

    def test_no_names_empty_list(self):
        c = _global(name_en="", aliases=[])
        assert c.all_names == []


# ===================================================================
#  type property
# ===================================================================

class TestTypeProperty:

    def test_global_type(self):
        assert _global().type == ContractorType.GLOBAL

    def test_ip_type(self):
        assert _ip().type == ContractorType.IP

    def test_samoz_type(self):
        assert _samoz().type == ContractorType.SAMOZANYATY


# ===================================================================
#  currency property
# ===================================================================

class TestCurrencyProperty:

    def test_global_currency_eur(self):
        assert _global().currency == Currency.EUR

    def test_ip_currency_rub(self):
        assert _ip().currency == Currency.RUB

    def test_samoz_currency_rub(self):
        assert _samoz().currency == Currency.RUB


# ===================================================================
#  SHEET_COLUMNS
# ===================================================================

class TestSheetColumns:

    def test_global_has_columns(self):
        assert len(GlobalContractor.SHEET_COLUMNS) > 0
        assert "id" in GlobalContractor.SHEET_COLUMNS
        assert "name_en" in GlobalContractor.SHEET_COLUMNS

    def test_ip_has_columns(self):
        assert len(IPContractor.SHEET_COLUMNS) > 0
        assert "id" in IPContractor.SHEET_COLUMNS
        assert "name_ru" in IPContractor.SHEET_COLUMNS
        assert "ogrnip" in IPContractor.SHEET_COLUMNS

    def test_samoz_has_columns(self):
        assert len(SamozanyatyContractor.SHEET_COLUMNS) > 0
        assert "id" in SamozanyatyContractor.SHEET_COLUMNS
        assert "inn" in SamozanyatyContractor.SHEET_COLUMNS

    def test_id_is_first_column_in_all(self):
        assert GlobalContractor.SHEET_COLUMNS[0] == "id"
        assert IPContractor.SHEET_COLUMNS[0] == "id"
        assert SamozanyatyContractor.SHEET_COLUMNS[0] == "id"


# ===================================================================
#  CONTRACTOR_CLASS_BY_TYPE mapping
# ===================================================================

class TestContractorClassByType:

    def test_all_types_mapped(self):
        from common.models import CONTRACTOR_CLASS_BY_TYPE
        assert ContractorType.GLOBAL in CONTRACTOR_CLASS_BY_TYPE
        assert ContractorType.IP in CONTRACTOR_CLASS_BY_TYPE
        assert ContractorType.SAMOZANYATY in CONTRACTOR_CLASS_BY_TYPE

    def test_correct_classes(self):
        from common.models import CONTRACTOR_CLASS_BY_TYPE
        assert CONTRACTOR_CLASS_BY_TYPE[ContractorType.GLOBAL] is GlobalContractor
        assert CONTRACTOR_CLASS_BY_TYPE[ContractorType.IP] is IPContractor
        assert CONTRACTOR_CLASS_BY_TYPE[ContractorType.SAMOZANYATY] is SamozanyatyContractor
