import pytest

from backend.infrastructure.repositories.contractor_repo import (
    _parse_contractor,
    _similarity,
    contractor_to_row,
    find_contractor_by_id,
    find_contractor_by_telegram_id,
    find_contractor_strict,
    fuzzy_find,
    next_contractor_id,
)
from common.models import (
    ContractorType,
    GlobalContractor,
    IPContractor,
    RoleCode,
    SamozanyatyContractor,
)


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _global(*, id="g1", name_en="Test Global", role_code=RoleCode.AUTHOR,
            aliases=None, telegram="", is_photographer=False):
    return GlobalContractor(
        id=id, name_en=name_en, address="Addr", email="a@b.c",
        bank_name="Bank", bank_account="ACC", swift="SWIFT",
        role_code=role_code, aliases=aliases or [],
        telegram=telegram, is_photographer=is_photographer,
    )


def _samoz(*, id="s1", name_ru="Тест Самозанятый", role_code=RoleCode.AUTHOR,
           aliases=None, telegram=""):
    return SamozanyatyContractor(
        id=id, name_ru=name_ru, address="Адрес", email="a@b.c",
        bank_name="Банк", bank_account="12345", bik="044525225",
        corr_account="30101810400000000225",
        passport_series="1234", passport_number="567890", inn="123456789012",
        role_code=role_code, aliases=aliases or [],
        telegram=telegram,
    )


# ===================================================================
#  _similarity
# ===================================================================

class TestSimilarity:

    def test_identical(self):
        assert _similarity("hello", "hello") == 1.0

    def test_empty_strings(self):
        assert _similarity("", "") == 1.0

    def test_completely_different(self):
        assert _similarity("abc", "xyz") < 0.5

    def test_case_insensitive(self):
        assert _similarity("ABC", "abc") == 1.0

    def test_whitespace_trimming(self):
        assert _similarity("  hello  ", "hello") == 1.0


# ===================================================================
#  fuzzy_find
# ===================================================================

class TestFuzzyFind:

    def test_exact_match(self):
        c = _global(name_en="Alice Johnson")
        results = fuzzy_find("Alice Johnson", [c])
        assert len(results) == 1
        assert results[0][0] is c
        assert results[0][1] >= 0.95

    def test_substring_query_in_name(self):
        c = _global(name_en="Alice Johnson")
        results = fuzzy_find("Alice", [c])
        assert len(results) == 1
        assert results[0][1] == 0.95

    def test_name_in_query(self):
        c = _global(name_en="Alice")
        results = fuzzy_find("Alice Johnson Writer", [c])
        assert len(results) == 1
        assert results[0][1] == 0.95

    def test_no_match(self):
        c = _global(name_en="Alice Johnson")
        results = fuzzy_find("Xyz Zzz", [c])
        assert results == []

    def test_multiple_matches_sorted(self):
        c1 = _global(id="g1", name_en="Alice Johnson")
        c2 = _global(id="g2", name_en="Alice Johansson")
        results = fuzzy_find("Alice Johnson", [c1, c2])
        assert len(results) == 2
        assert results[0][1] >= results[1][1]
        assert results[0][0] is c1

    def test_alias_match(self):
        c = _global(name_en="Official Name", aliases=["Nickname"])
        results = fuzzy_find("Nickname", [c])
        assert len(results) == 1
        assert results[0][0] is c

    def test_below_threshold_not_returned(self):
        c = _global(name_en="Alice Johnson")
        results = fuzzy_find("Xyz", [c], threshold=0.9)
        assert results == []


# ===================================================================
#  find_contractor_by_id
# ===================================================================

class TestFindContractorById:

    def test_found(self):
        c = _global(id="g42")
        assert find_contractor_by_id("g42", [c]) is c

    def test_not_found(self):
        c = _global(id="g1")
        assert find_contractor_by_id("g99", [c]) is None

    def test_empty_list(self):
        assert find_contractor_by_id("g1", []) is None


# ===================================================================
#  find_contractor_strict
# ===================================================================

class TestFindContractorStrict:

    def test_exact_match_case_insensitive(self):
        c = _global(name_en="Alice Johnson")
        assert find_contractor_strict("alice johnson", [c]) is c

    def test_no_exact_match(self):
        c = _global(name_en="Alice Johnson")
        assert find_contractor_strict("Alice Jo", [c]) is None

    def test_matches_on_alias(self):
        c = _global(name_en="Official", aliases=["Nickname"])
        assert find_contractor_strict("nickname", [c]) is c


# ===================================================================
#  find_contractor_by_telegram_id
# ===================================================================

class TestFindContractorByTelegramId:

    def test_found(self):
        c = _global(telegram="12345")
        assert find_contractor_by_telegram_id(12345, [c]) is c

    def test_not_found(self):
        c = _global(telegram="12345")
        assert find_contractor_by_telegram_id(99999, [c]) is None


# ===================================================================
#  next_contractor_id
# ===================================================================

class TestNextContractorId:

    def test_empty_list(self):
        assert next_contractor_id([]) == "c001"

    def test_existing_ids(self):
        cs = [_global(id="c001"), _global(id="c005")]
        assert next_contractor_id(cs) == "c006"

    def test_non_standard_ids_ignored(self):
        cs = [_global(id="c003"), _global(id="xyz")]
        assert next_contractor_id(cs) == "c004"


# ===================================================================
#  contractor_to_row
# ===================================================================

class TestContractorToRow:

    def test_global_columns(self):
        c = _global(name_en="John Doe")
        row = contractor_to_row(c)
        cols = GlobalContractor.SHEET_COLUMNS
        assert row[cols.index("id")] == "g1"
        assert row[cols.index("name_en")] == "John Doe"
        assert row[cols.index("email")] == "a@b.c"
        assert row[cols.index("swift")] == "SWIFT"

    def test_samoz_columns(self):
        c = _samoz(name_ru="Иван Петров")
        row = contractor_to_row(c)
        cols = SamozanyatyContractor.SHEET_COLUMNS
        assert row[cols.index("id")] == "s1"
        assert row[cols.index("name_ru")] == "Иван Петров"
        assert row[cols.index("inn")] == "123456789012"

    def test_aliases_joined(self):
        c = _global(aliases=["Nick1", "Nick2"])
        row = contractor_to_row(c)
        cols = GlobalContractor.SHEET_COLUMNS
        assert row[cols.index("aliases")] == "Nick1, Nick2"

    def test_role_code_with_photographer(self):
        c = _global(role_code=RoleCode.AUTHOR, is_photographer=True)
        row = contractor_to_row(c)
        cols = GlobalContractor.SHEET_COLUMNS
        assert row[cols.index("role_code")] == "A:F"


# ===================================================================
#  _parse_contractor
# ===================================================================

class TestParseContractor:

    def test_valid_global(self):
        row = {
            "id": "g1", "name_en": "John Doe", "email": "j@d.com",
            "bank_name": "Bank", "bank_account": "ACC", "swift": "SWIFT",
            "address": "Addr", "role_code": "A",
        }
        c = _parse_contractor(row, ContractorType.GLOBAL)
        assert isinstance(c, GlobalContractor)
        assert c.id == "g1"
        assert c.name_en == "John Doe"

    def test_valid_samozanyaty(self):
        row = {
            "id": "s1", "name_ru": "Иван", "email": "i@v.ru",
            "bank_name": "Банк", "bank_account": "12345", "bik": "044525225",
            "corr_account": "30101810400000000225",
            "passport_series": "1234", "passport_number": "567890",
            "inn": "123456789012", "address": "Адрес",
            "role_code": "A",
        }
        c = _parse_contractor(row, ContractorType.SAMOZANYATY)
        assert isinstance(c, SamozanyatyContractor)
        assert c.name_ru == "Иван"

    def test_photographer_flag(self):
        row = {
            "id": "g1", "name_en": "John", "email": "j@d.com",
            "bank_name": "B", "bank_account": "A", "swift": "S",
            "address": "X", "role_code": "A:F",
        }
        c = _parse_contractor(row, ContractorType.GLOBAL)
        assert c.is_photographer is True
        assert c.role_code == RoleCode.AUTHOR

    def test_invalid_role_defaults_to_author(self):
        row = {
            "id": "g1", "name_en": "John", "email": "j@d.com",
            "bank_name": "B", "bank_account": "A", "swift": "S",
            "address": "X", "role_code": "ZZZ",
        }
        c = _parse_contractor(row, ContractorType.GLOBAL)
        assert c.role_code == RoleCode.AUTHOR

    def test_missing_id_returns_object_with_empty_id(self):
        row = {
            "name_en": "John", "email": "j@d.com",
            "bank_name": "B", "bank_account": "A", "swift": "S",
            "address": "X",
        }
        c = _parse_contractor(row, ContractorType.GLOBAL)
        assert c is not None
        assert c.id == ""

    def test_missing_fields_default_to_empty(self):
        row = {"id": "g1"}
        c = _parse_contractor(row, ContractorType.GLOBAL)
        assert c is not None
        assert c.name_en == ""
        assert c.swift == ""

    def test_aliases_parsed(self):
        row = {
            "id": "g1", "name_en": "John", "email": "j@d.com",
            "bank_name": "B", "bank_account": "A", "swift": "S",
            "address": "X", "aliases": "Nick1, Nick2",
        }
        c = _parse_contractor(row, ContractorType.GLOBAL)
        assert c.aliases == ["Nick1", "Nick2"]

    def test_aliases_empty_string(self):
        row = {
            "id": "g1", "name_en": "John", "email": "j@d.com",
            "bank_name": "B", "bank_account": "A", "swift": "S",
            "address": "X", "aliases": "",
        }
        c = _parse_contractor(row, ContractorType.GLOBAL)
        assert c.aliases == []
