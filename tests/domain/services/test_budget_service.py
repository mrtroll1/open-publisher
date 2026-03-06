"""Tests for backend/domain/services/budget_service.py."""

from unittest.mock import MagicMock, call, patch

from common.models import Currency
from backend.commands.budget.redirect import (
    EUR_RUB_RATE,
    _add_amount_to_row,
    _convert_amount,
    _extract_bonus_from_note,
    _find_row_by_name,
    _find_source_row,
    _pad_row,
    _restore_source_row,
    _subtract_amount_from_row,
    redirect_in_budget,
    unredirect_in_budget,
)


# ===================================================================
#  _find_row_by_name — pure logic
# ===================================================================

class TestFindRowByName:

    def test_exact_match(self):
        rows = [["Alice", "", "100"], ["Bob", "", "200"]]
        assert _find_row_by_name(rows, "Alice") == 0

    def test_case_insensitive(self):
        rows = [["alice"], ["BOB"]]
        assert _find_row_by_name(rows, "Alice") == 0
        assert _find_row_by_name(rows, "bob") == 1

    def test_whitespace_stripped(self):
        rows = [["  Alice  "]]
        assert _find_row_by_name(rows, " Alice ") == 0

    def test_not_found(self):
        rows = [["Alice"], ["Bob"]]
        assert _find_row_by_name(rows, "Charlie") is None

    def test_empty_rows_skipped(self):
        rows = [[], ["Alice"]]
        assert _find_row_by_name(rows, "Alice") == 1

    def test_empty_list(self):
        assert _find_row_by_name([], "Alice") is None

    def test_returns_first_match(self):
        rows = [["Alice"], ["Alice"]]
        assert _find_row_by_name(rows, "Alice") == 0


# ===================================================================
#  _find_source_row — pure logic
# ===================================================================

class TestFindSourceRow:

    def test_found_with_both_amounts(self):
        rows = [["Alice", "", "500", "30000"]]
        idx, eur, rub = _find_source_row(rows, "Alice")
        assert idx == 0
        assert eur == 500
        assert rub == 30000

    def test_case_insensitive(self):
        rows = [["alice", "", "100", "5000"]]
        idx, eur, rub = _find_source_row(rows, "ALICE")
        assert idx == 0
        assert eur == 100

    def test_missing_eur_column(self):
        rows = [["Alice", "info"]]
        idx, eur, rub = _find_source_row(rows, "Alice")
        assert idx == 0
        assert eur == 0
        assert rub == 0

    def test_missing_rub_column(self):
        rows = [["Alice", "", "300"]]
        idx, eur, rub = _find_source_row(rows, "Alice")
        assert idx == 0
        assert eur == 300
        assert rub == 0

    def test_not_found(self):
        rows = [["Bob", "", "100"]]
        idx, eur, rub = _find_source_row(rows, "Alice")
        assert idx is None
        assert eur == 0
        assert rub == 0

    def test_empty_rows_skipped(self):
        rows = [[], ["", ""], ["Alice", "", "100", "200"]]
        idx, eur, rub = _find_source_row(rows, "Alice")
        assert idx == 2
        assert eur == 100

    def test_blank_name_rows_skipped(self):
        rows = [["  ", "", "999"], ["Alice", "", "50"]]
        idx, eur, rub = _find_source_row(rows, "Alice")
        assert idx == 1
        assert eur == 50

    def test_empty_list(self):
        idx, eur, rub = _find_source_row([], "Alice")
        assert idx is None


# ===================================================================
#  _convert_amount — pure logic
# ===================================================================

class TestConvertAmount:

    def test_eur_to_eur(self):
        assert _convert_amount(500, 0, Currency.EUR) == 500

    def test_rub_to_rub(self):
        assert _convert_amount(0, 30000, Currency.RUB) == 30000

    def test_rub_to_eur_conversion(self):
        assert _convert_amount(0, EUR_RUB_RATE * 5, Currency.EUR) == 5

    def test_eur_to_rub_conversion(self):
        assert _convert_amount(5, 0, Currency.RUB) == 5 * EUR_RUB_RATE

    def test_eur_preferred_when_target_eur(self):
        # source has both — EUR takes priority when target is EUR
        assert _convert_amount(500, 30000, Currency.EUR) == 500

    def test_rub_preferred_when_target_rub(self):
        # source has both — RUB takes priority when target is RUB
        assert _convert_amount(500, 30000, Currency.RUB) == 30000

    def test_both_zero(self):
        assert _convert_amount(0, 0, Currency.EUR) == 0
        assert _convert_amount(0, 0, Currency.RUB) == 0

    def test_eur_zero_rub_zero_target_eur(self):
        assert _convert_amount(0, 0, Currency.EUR) == 0

    def test_eur_zero_rub_zero_target_rub(self):
        assert _convert_amount(0, 0, Currency.RUB) == 0


# ===================================================================
#  _pad_row — pure logic
# ===================================================================

class TestPadRow:

    def test_empty_row(self):
        assert _pad_row([]) == ["", "", "", "", ""]

    def test_short_row(self):
        assert _pad_row(["A", "B"]) == ["A", "B", "", "", ""]

    def test_already_full(self):
        assert _pad_row(["a", "b", "c", "d", "e"]) == ["a", "b", "c", "d", "e"]

    def test_single_element(self):
        assert _pad_row(["X"]) == ["X", "", "", "", ""]

    def test_four_elements(self):
        assert _pad_row(["a", "b", "c", "d"]) == ["a", "b", "c", "d", ""]


# ===================================================================
#  _add_amount_to_row — pure logic
# ===================================================================

class TestAddAmountToRow:

    def test_eur_column(self):
        row = ["Name", "", "100", "0", ""]
        _add_amount_to_row(row, 50, Currency.EUR)
        assert row[2] == "150"

    def test_rub_column(self):
        row = ["Name", "", "0", "5000", ""]
        _add_amount_to_row(row, 3000, Currency.RUB)
        assert row[3] == "8000"

    def test_cumulative(self):
        row = ["Name", "", "200", "0", ""]
        _add_amount_to_row(row, 100, Currency.EUR)
        _add_amount_to_row(row, 50, Currency.EUR)
        assert row[2] == "350"

    def test_empty_cell_treated_as_zero(self):
        row = ["Name", "", "", "", ""]
        _add_amount_to_row(row, 100, Currency.EUR)
        assert row[2] == "100"


# ===================================================================
#  _subtract_amount_from_row — pure logic
# ===================================================================

class TestSubtractAmountFromRow:

    def test_eur_column(self):
        row = ["Name", "", "500", "0", ""]
        _subtract_amount_from_row(row, 200, Currency.EUR)
        assert row[2] == "300"

    def test_rub_column(self):
        row = ["Name", "", "0", "10000", ""]
        _subtract_amount_from_row(row, 3000, Currency.RUB)
        assert row[3] == "7000"

    def test_negative_result(self):
        row = ["Name", "", "100", "0", ""]
        _subtract_amount_from_row(row, 200, Currency.EUR)
        assert row[2] == "-100"

    def test_empty_cell_treated_as_zero(self):
        row = ["Name", "", "", "", ""]
        _subtract_amount_from_row(row, 50, Currency.RUB)
        assert row[3] == "-50"


# ===================================================================
#  _extract_bonus_from_note — pure logic
# ===================================================================

class TestExtractBonusFromNote:

    def test_single_match(self):
        amount, note = _extract_bonus_from_note("Alice (500)", "Alice")
        assert amount == 500
        assert note == ""

    def test_multiple_entries_extracts_correct_one(self):
        amount, note = _extract_bonus_from_note("Alice (500), Bob (300)", "Alice")
        assert amount == 500
        assert note == "Bob (300)"

    def test_case_insensitive(self):
        amount, note = _extract_bonus_from_note("alice (200)", "ALICE")
        assert amount == 200

    def test_no_match(self):
        amount, note = _extract_bonus_from_note("Bob (300)", "Alice")
        assert amount == 0
        assert note == "Bob (300)"

    def test_invalid_amount_keeps_entry(self):
        amount, note = _extract_bonus_from_note("Alice (abc)", "Alice")
        assert amount == 0
        assert note == "Alice (abc)"

    def test_no_parens_entry_preserved(self):
        amount, note = _extract_bonus_from_note("some note, Alice (100)", "Alice")
        assert amount == 100
        assert note == "some note"

    def test_empty_note(self):
        amount, note = _extract_bonus_from_note("", "Alice")
        assert amount == 0
        assert note == ""

    def test_multiple_entries_middle_match(self):
        amount, note = _extract_bonus_from_note(
            "Bob (100), Alice (200), Charlie (300)", "Alice",
        )
        assert amount == 200
        assert note == "Bob (100), Charlie (300)"

    def test_whitespace_in_source_name(self):
        amount, note = _extract_bonus_from_note("Alice (500)", " Alice ")
        assert amount == 500


# ===================================================================
#  redirect_in_budget — mocked orchestration
# ===================================================================

class TestRedirectInBudget:

    def _make_target(self, name="Target", currency=Currency.EUR):
        t = MagicMock()
        t.display_name = name
        t.currency = currency
        return t

    @patch("backend.commands.budget.redirect._find_sheet", return_value=None)
    def test_no_sheet_returns_early(self, mock_find):
        target = self._make_target()
        redirect_in_budget("Source", target, "2026-01")
        mock_find.assert_called_once_with("2026-01")

    @patch("backend.commands.budget.redirect._sheets")
    @patch("backend.commands.budget.redirect._find_sheet", return_value="sheet123")
    def test_source_not_found_skips(self, mock_find, mock_sheets):
        mock_sheets.read.return_value = [["Target", "", "0", "0", ""]]
        target = self._make_target()
        redirect_in_budget("Unknown", target, "2026-01")
        mock_sheets.write.assert_not_called()
        mock_sheets.clear.assert_not_called()

    @patch("backend.commands.budget.redirect._sheets")
    @patch("backend.commands.budget.redirect._find_sheet", return_value="sheet123")
    def test_target_not_found_skips(self, mock_find, mock_sheets):
        mock_sheets.read.return_value = [["Source", "", "500", "0", ""]]
        target = self._make_target(name="Missing")
        redirect_in_budget("Source", target, "2026-01")
        mock_sheets.write.assert_not_called()

    @patch("backend.commands.budget.redirect._sheets")
    @patch("backend.commands.budget.redirect._find_sheet", return_value="sheet123")
    def test_zero_amounts_skips(self, mock_find, mock_sheets):
        mock_sheets.read.return_value = [
            ["Source", "", "0", "0", ""],
            ["Target", "", "100", "0", ""],
        ]
        target = self._make_target()
        redirect_in_budget("Source", target, "2026-01")
        mock_sheets.write.assert_not_called()

    @patch("backend.commands.budget.redirect._sheets")
    @patch("backend.commands.budget.redirect._find_sheet", return_value="sheet123")
    def test_happy_path_eur(self, mock_find, mock_sheets):
        mock_sheets.read.return_value = [
            ["Source", "", "500", "0", ""],
            ["Target", "", "200", "0", ""],
        ]
        target = self._make_target(name="Target", currency=Currency.EUR)
        redirect_in_budget("Source", target, "2026-01")

        # Target row updated: 200 + 500 = 700, note = "Source (500)"
        mock_sheets.write.assert_called_once_with(
            "sheet123", "A3:E3",
            [["Target", "", "700", "0", "Source (500)"]],
        )
        # Source row cleared
        mock_sheets.clear.assert_called_once_with("sheet123", "A2:E2")

    @patch("backend.commands.budget.redirect._sheets")
    @patch("backend.commands.budget.redirect._find_sheet", return_value="sheet123")
    def test_happy_path_rub(self, mock_find, mock_sheets):
        mock_sheets.read.return_value = [
            ["Source", "", "0", "30000", ""],
            ["Target", "", "0", "10000", ""],
        ]
        target = self._make_target(name="Target", currency=Currency.RUB)
        redirect_in_budget("Source", target, "2026-01")

        mock_sheets.write.assert_called_once_with(
            "sheet123", "A3:E3",
            [["Target", "", "0", "40000", "Source (30000)"]],
        )
        mock_sheets.clear.assert_called_once_with("sheet123", "A2:E2")

    @patch("backend.commands.budget.redirect._sheets")
    @patch("backend.commands.budget.redirect._find_sheet", return_value="sheet123")
    def test_note_appended_to_existing(self, mock_find, mock_sheets):
        mock_sheets.read.return_value = [
            ["Source", "", "100", "0", ""],
            ["Target", "", "200", "0", "Old (50)"],
        ]
        target = self._make_target(name="Target", currency=Currency.EUR)
        redirect_in_budget("Source", target, "2026-01")

        written_row = mock_sheets.write.call_args[0][2][0]
        assert written_row[4] == "Old (50), Source (100)"

    @patch("backend.commands.budget.redirect._sheets")
    @patch("backend.commands.budget.redirect._find_sheet", return_value="sheet123")
    def test_cross_currency_eur_source_rub_target(self, mock_find, mock_sheets):
        mock_sheets.read.return_value = [
            ["Source", "", "5", "0", ""],
            ["Target", "", "0", "10000", ""],
        ]
        target = self._make_target(name="Target", currency=Currency.RUB)
        redirect_in_budget("Source", target, "2026-01")

        expected_amount = 5 * EUR_RUB_RATE
        written_row = mock_sheets.write.call_args[0][2][0]
        assert written_row[3] == str(10000 + expected_amount)

    @patch("backend.commands.budget.redirect._sheets")
    @patch("backend.commands.budget.redirect._find_sheet", return_value="sheet123")
    def test_short_rows_padded(self, mock_find, mock_sheets):
        mock_sheets.read.return_value = [
            ["Source", "", "100"],
            ["Target"],
        ]
        target = self._make_target(name="Target", currency=Currency.EUR)
        redirect_in_budget("Source", target, "2026-01")

        written_row = mock_sheets.write.call_args[0][2][0]
        assert len(written_row) == 5


# ===================================================================
#  unredirect_in_budget — mocked orchestration
# ===================================================================

class TestUnredirectInBudget:

    def _make_target(self, name="Target", currency=Currency.EUR):
        t = MagicMock()
        t.display_name = name
        t.currency = currency
        return t

    @patch("backend.commands.budget.redirect._find_sheet", return_value=None)
    def test_no_sheet_returns_early(self, mock_find):
        target = self._make_target()
        unredirect_in_budget("Source", target, "2026-01")
        mock_find.assert_called_once_with("2026-01")

    @patch("backend.commands.budget.redirect._sheets")
    @patch("backend.commands.budget.redirect._find_sheet", return_value="sheet123")
    def test_target_not_found_skips(self, mock_find, mock_sheets):
        mock_sheets.read.return_value = [["Other", "", "100", "0", ""]]
        target = self._make_target(name="Missing")
        unredirect_in_budget("Source", target, "2026-01")
        mock_sheets.write.assert_not_called()

    @patch("backend.commands.budget.redirect._sheets")
    @patch("backend.commands.budget.redirect._find_sheet", return_value="sheet123")
    def test_empty_note_skips(self, mock_find, mock_sheets):
        mock_sheets.read.return_value = [["Target", "", "500", "0", ""]]
        target = self._make_target()
        unredirect_in_budget("Source", target, "2026-01")
        mock_sheets.write.assert_not_called()

    @patch("backend.commands.budget.redirect._sheets")
    @patch("backend.commands.budget.redirect._find_sheet", return_value="sheet123")
    def test_source_not_in_note_skips(self, mock_find, mock_sheets):
        mock_sheets.read.return_value = [["Target", "", "500", "0", "Bob (200)"]]
        target = self._make_target()
        unredirect_in_budget("Alice", target, "2026-01")
        mock_sheets.write.assert_not_called()

    @patch("backend.commands.budget.redirect._sheets")
    @patch("backend.commands.budget.redirect._find_sheet", return_value="sheet123")
    def test_happy_path_eur(self, mock_find, mock_sheets):
        mock_sheets.read.return_value = [
            ["Target", "", "700", "0", "Source (500)"],
        ]
        target = self._make_target(name="Target", currency=Currency.EUR)
        unredirect_in_budget("Source", target, "2026-01")

        # Target row: 700 - 500 = 200, note cleared
        calls = mock_sheets.write.call_args_list
        assert calls[0] == call("sheet123", "A2:E2", [["Target", "", "200", "0", ""]])
        # Source restored in empty slot (rows length = 1, so empty_idx = 1)
        assert calls[1] == call("sheet123", "A3:E3", [["Source", "", "500", "", ""]])

    @patch("backend.commands.budget.redirect._sheets")
    @patch("backend.commands.budget.redirect._find_sheet", return_value="sheet123")
    def test_happy_path_rub(self, mock_find, mock_sheets):
        mock_sheets.read.return_value = [
            ["Target", "", "0", "40000", "Source (30000)"],
        ]
        target = self._make_target(name="Target", currency=Currency.RUB)
        unredirect_in_budget("Source", target, "2026-01")

        calls = mock_sheets.write.call_args_list
        assert calls[0] == call(
            "sheet123", "A2:E2",
            [["Target", "", "0", "10000", ""]],
        )
        assert calls[1] == call(
            "sheet123", "A3:E3",
            [["Source", "", "", "30000", ""]],
        )

    @patch("backend.commands.budget.redirect._sheets")
    @patch("backend.commands.budget.redirect._find_sheet", return_value="sheet123")
    def test_remaining_note_preserved(self, mock_find, mock_sheets):
        mock_sheets.read.return_value = [
            ["Target", "", "1000", "0", "Alice (300), Source (200), Bob (500)"],
        ]
        target = self._make_target(name="Target", currency=Currency.EUR)
        unredirect_in_budget("Source", target, "2026-01")

        written_row = mock_sheets.write.call_args_list[0][0][2][0]
        assert written_row[2] == "800"
        assert written_row[4] == "Alice (300), Bob (500)"


# ===================================================================
#  _restore_source_row — mocked _sheets
# ===================================================================

class TestRestoreSourceRow:

    @patch("backend.commands.budget.redirect._sheets")
    def test_empty_slot_found(self, mock_sheets):
        rows = [["Alice", "", "100"], [], ["Bob", "", "200"]]
        _restore_source_row("sheet123", rows, "Source", 500, Currency.EUR)
        mock_sheets.write.assert_called_once_with(
            "sheet123", "A3:E3",
            [["Source", "", "500", "", ""]],
        )

    @patch("backend.commands.budget.redirect._sheets")
    def test_no_empty_slot_appends(self, mock_sheets):
        rows = [["Alice", "", "100"], ["Bob", "", "200"]]
        _restore_source_row("sheet123", rows, "Source", 500, Currency.EUR)
        mock_sheets.write.assert_called_once_with(
            "sheet123", "A4:E4",
            [["Source", "", "500", "", ""]],
        )

    @patch("backend.commands.budget.redirect._sheets")
    def test_eur_column(self, mock_sheets):
        rows = [["Alice"]]
        _restore_source_row("sheet123", rows, "Source", 300, Currency.EUR)
        written_row = mock_sheets.write.call_args[0][2][0]
        assert written_row[2] == "300"
        assert written_row[3] == ""

    @patch("backend.commands.budget.redirect._sheets")
    def test_rub_column(self, mock_sheets):
        rows = [["Alice"]]
        _restore_source_row("sheet123", rows, "Source", 5000, Currency.RUB)
        written_row = mock_sheets.write.call_args[0][2][0]
        assert written_row[2] == ""
        assert written_row[3] == "5000"

    @patch("backend.commands.budget.redirect._sheets")
    def test_blank_name_row_is_empty_slot(self, mock_sheets):
        rows = [["Alice", "", "100"], ["  ", "", ""], ["Bob"]]
        _restore_source_row("sheet123", rows, "Source", 100, Currency.EUR)
        # Row index 1 has blank name => treated as empty
        mock_sheets.write.assert_called_once_with(
            "sheet123", "A3:E3",
            [["Source", "", "100", "", ""]],
        )
