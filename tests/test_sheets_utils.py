import pytest

from backend.infrastructure.repositories.sheets_utils import (
    index_to_column_letter,
    parse_int,
)


# ===================================================================
#  index_to_column_letter
# ===================================================================

class TestIndexToColumnLetter:

    @pytest.mark.parametrize(
        "idx, expected",
        [
            (0, "A"),
            (1, "B"),
            (2, "C"),
            (25, "Z"),
        ],
        ids=["A", "B", "C", "Z"],
    )
    def test_single_letter_columns(self, idx, expected):
        assert index_to_column_letter(idx) == expected

    @pytest.mark.parametrize(
        "idx, expected",
        [
            (26, "AA"),
            (27, "AB"),
            (51, "AZ"),
            (52, "BA"),
        ],
        ids=["AA", "AB", "AZ", "BA"],
    )
    def test_double_letter_columns(self, idx, expected):
        assert index_to_column_letter(idx) == expected

    def test_triple_letter_column(self):
        # 26^2 + 26 = 702 → AAA (index 702)
        assert index_to_column_letter(702) == "AAA"

    def test_column_26_is_AA(self):
        # 0=A, 1=B, ..., 25=Z, 26=AA
        assert index_to_column_letter(26) == "AA"

    def test_sequential_progression(self):
        letters = [index_to_column_letter(i) for i in range(5)]
        assert letters == ["A", "B", "C", "D", "E"]


# ===================================================================
#  parse_int
# ===================================================================

class TestParseInt:

    def test_valid_integer(self):
        assert parse_int("42") == 42

    def test_negative_integer(self):
        assert parse_int("-5") == -5

    def test_zero(self):
        assert parse_int("0") == 0

    def test_empty_string(self):
        assert parse_int("") == 0

    def test_whitespace_only(self):
        assert parse_int("   ") == 0

    def test_whitespace_around_number(self):
        assert parse_int("  123  ") == 123

    def test_non_numeric_string(self):
        assert parse_int("abc") == 0

    def test_float_string(self):
        assert parse_int("3.14") == 0

    def test_mixed_content(self):
        assert parse_int("12abc") == 0

    def test_large_number(self):
        assert parse_int("999999") == 999999
