"""Tests for ContractorFactory."""

from unittest.mock import MagicMock, patch

from backend.commands.contractor.create import ContractorFactory


class TestCheckComplete:
    def test_all_present(self):
        ok, missing = ContractorFactory().check_complete(
            {"name": "John", "email": "j@x.com"},
            {"name": "ФИО", "email": "Email"},
        )
        assert ok is True
        assert missing == {}

    def test_missing_field(self):
        ok, missing = ContractorFactory().check_complete(
            {"name": "John"},
            {"name": "ФИО", "email": "Email"},
        )
        assert ok is False
        assert "email" in missing

    def test_blank_treated_as_missing(self):
        ok, _ = ContractorFactory().check_complete(
            {"name": "John", "email": "  "},
            {"name": "ФИО", "email": "Email"},
        )
        assert ok is False


class TestCreate:
    @patch("backend.commands.contractor.create.save_contractor")
    @patch("backend.commands.contractor.create.pop_random_secret_code", return_value="XYZ")
    @patch("backend.commands.contractor.create.next_contractor_id", return_value="c42")
    @patch("backend.commands.contractor.create.CONTRACTOR_CLASS_BY_TYPE")
    def test_saves_and_returns_code(self, mock_types, _next, _code, mock_save):
        mock_cls = MagicMock()
        mock_cls.FIELD_META = ["extra_field"]
        mock_instance = MagicMock()
        mock_instance.display_name = "Test"
        mock_cls.return_value = mock_instance
        mock_types.__getitem__ = lambda _self, _key: mock_cls

        contractor, code = ContractorFactory().create(
            {"name": "Test", "aliases": ["A"]}, "samozanyaty", "tg1", [])

        assert code == "XYZ"
        assert contractor is mock_instance
        mock_save.assert_called_once_with(mock_instance)
