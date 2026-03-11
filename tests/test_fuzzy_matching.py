from unittest.mock import MagicMock

from backend.infrastructure.repositories.sheets.contractor_repo import (
    _word_independent_score,
    fuzzy_find,
)


def _make_contractor(name):
    c = MagicMock()
    c.all_names = [name]
    return c


def test_word_order_ru():
    matches = fuzzy_find("Иванов Петр", [_make_contractor("Петр Иванов")])
    assert len(matches) == 1
    assert matches[0][1] >= 0.8


def test_word_order_en():
    matches = fuzzy_find("Smith John", [_make_contractor("John Smith")])
    assert len(matches) == 1
    assert matches[0][1] >= 0.8


def test_substring_still_works():
    matches = fuzzy_find("Иван", [_make_contractor("Иванов")])
    assert len(matches) == 1
    assert matches[0][1] == 0.95


def test_threshold_respected():
    matches = fuzzy_find("xyz", [_make_contractor("Петр Иванов")], threshold=0.9)
    assert matches == []


def test_low_threshold_catches_loose():
    matches = fuzzy_find("Иван", [_make_contractor("Иванов Петр Сергеевич")], threshold=0.6)
    assert len(matches) >= 1


def test_word_independent_score_basic():
    assert _word_independent_score("Петр Иванов", "Иванов Петр") == 1.0
