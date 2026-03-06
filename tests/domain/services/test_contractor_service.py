"""Tests for backend/domain/services/contractor_service.py."""

from unittest.mock import MagicMock, patch

from common.models import ContractorType, SamozanyatyContractor


# ===================================================================
#  check_registration_complete — pure logic, no mocks
# ===================================================================

class TestCheckRegistrationComplete:

    def _check(self, collected, required):
        from backend.commands.contractor.create import check_registration_complete
        return check_registration_complete(collected, required)

    def test_all_filled(self):
        collected = {"name_ru": "Иванов", "email": "a@b.c"}
        required = {"name_ru": "ФИО", "email": "email"}
        is_complete, missing = self._check(collected, required)
        assert is_complete is True
        assert missing == {}

    def test_some_missing(self):
        collected = {"name_ru": "Иванов"}
        required = {"name_ru": "ФИО", "email": "email"}
        is_complete, missing = self._check(collected, required)
        assert is_complete is False
        assert missing == {"email": "email"}

    def test_all_missing(self):
        collected = {}
        required = {"name_ru": "ФИО", "email": "email"}
        is_complete, missing = self._check(collected, required)
        assert is_complete is False
        assert "name_ru" in missing
        assert "email" in missing

    def test_whitespace_treated_as_missing(self):
        collected = {"name_ru": "  ", "email": "a@b.c"}
        required = {"name_ru": "ФИO", "email": "email"}
        is_complete, missing = self._check(collected, required)
        assert is_complete is False
        assert "name_ru" in missing

    def test_empty_string_treated_as_missing(self):
        collected = {"name_ru": "", "email": "a@b.c"}
        required = {"name_ru": "ФИО", "email": "email"}
        is_complete, missing = self._check(collected, required)
        assert is_complete is False
        assert "name_ru" in missing

    def test_empty_required_means_always_complete(self):
        collected = {}
        required = {}
        is_complete, missing = self._check(collected, required)
        assert is_complete is True
        assert missing == {}

    def test_extra_fields_ignored(self):
        collected = {"name_ru": "Иванов", "email": "a@b.c", "extra": "val"}
        required = {"name_ru": "ФИО", "email": "email"}
        is_complete, missing = self._check(collected, required)
        assert is_complete is True


# ===================================================================
#  parse_registration_data — mock parse_contractor_data and DbGateway
# ===================================================================

class TestParseRegistrationData:

    @patch("backend.commands.contractor.registration.DbGateway")
    @patch("backend.commands.contractor.registration.parse_contractor_data")
    def test_success_logs_to_db(self, mock_parse, MockDb):
        from backend.commands.contractor.registration import parse_registration_data

        mock_parse.return_value = {"name_ru": "Иванов"}
        mock_db = MockDb.return_value
        mock_db.log_payment_validation.return_value = "val-123"

        result = parse_registration_data(
            "Иванов Иван", ContractorType.SAMOZANYATY,
        )

        assert result["name_ru"] == "Иванов"
        assert result["_validation_id"] == "val-123"
        mock_db.log_payment_validation.assert_called_once()

    @patch("backend.commands.contractor.registration.DbGateway")
    @patch("backend.commands.contractor.registration.parse_contractor_data")
    def test_parse_error_skips_db_logging(self, mock_parse, MockDb):
        from backend.commands.contractor.registration import parse_registration_data

        mock_parse.return_value = {"parse_error": "bad input"}

        result = parse_registration_data(
            "??", ContractorType.SAMOZANYATY,
        )

        assert "parse_error" in result
        MockDb.return_value.log_payment_validation.assert_not_called()

    @patch("backend.commands.contractor.registration.DbGateway")
    @patch("backend.commands.contractor.registration.parse_contractor_data")
    def test_db_error_swallowed(self, mock_parse, MockDb):
        from backend.commands.contractor.registration import parse_registration_data

        mock_parse.return_value = {"name_ru": "Иванов"}
        MockDb.return_value.log_payment_validation.side_effect = RuntimeError("db down")

        result = parse_registration_data(
            "Иванов", ContractorType.SAMOZANYATY,
        )

        assert result["name_ru"] == "Иванов"
        assert "_validation_id" not in result

    @patch("backend.commands.contractor.registration.DbGateway")
    @patch("backend.commands.contractor.registration.parse_contractor_data")
    def test_context_built_from_collected(self, mock_parse, MockDb):
        from backend.commands.contractor.registration import parse_registration_data

        mock_parse.return_value = {"email": "a@b.c"}
        MockDb.return_value.log_payment_validation.return_value = "v1"

        parse_registration_data(
            "email: a@b.c", ContractorType.SAMOZANYATY,
            collected={"name_ru": "Иванов"},
        )

        call_args = mock_parse.call_args
        context = call_args[0][2]
        assert "Иванов" in context

    @patch("backend.commands.contractor.registration.DbGateway")
    @patch("backend.commands.contractor.registration.parse_contractor_data")
    def test_warnings_included_in_context(self, mock_parse, MockDb):
        from backend.commands.contractor.registration import parse_registration_data

        mock_parse.return_value = {"inn": "123456"}
        MockDb.return_value.log_payment_validation.return_value = "v1"

        parse_registration_data(
            "инн: 123456", ContractorType.SAMOZANYATY,
            collected={"name_ru": "Иванов"},
            warnings=["ИНН: неверная длина"],
        )

        call_args = mock_parse.call_args
        context = call_args[0][2]
        assert "ИНН: неверная длина" in context


# ===================================================================
#  create_contractor — mock next_contractor_id, save_contractor, pop_random_secret_code
# ===================================================================

class TestCreateContractor:

    @patch("backend.commands.contractor.create.pop_random_secret_code", return_value="ABC123")
    @patch("backend.commands.contractor.create.save_contractor")
    @patch("backend.commands.contractor.create.next_contractor_id", return_value="C042")
    def test_success(self, mock_next_id, mock_save, mock_code):
        from backend.commands.contractor.create import create_contractor

        collected = {
            "name_ru": "Иванов Иван",
            "email": "ivan@test.ru",
            "bank_name": "Сбер",
            "bank_account": "40802810",
            "address": "Москва",
            "passport_series": "1234",
            "passport_number": "567890",
            "inn": "123456789012",
            "bik": "044525225",
            "corr_account": "30101810400000000225",
            "aliases": ["Иванов"],
        }

        contractor, code = create_contractor(
            collected, ContractorType.SAMOZANYATY, "12345", [],
        )

        assert contractor is not None
        assert isinstance(contractor, SamozanyatyContractor)
        assert contractor.id == "C042"
        assert contractor.secret_code == "ABC123"
        assert contractor.telegram == "12345"
        assert code == "ABC123"
        mock_save.assert_called_once_with(contractor)

    @patch("backend.commands.contractor.create.pop_random_secret_code", return_value="X")
    @patch("backend.commands.contractor.create.save_contractor", side_effect=RuntimeError("boom"))
    @patch("backend.commands.contractor.create.next_contractor_id", return_value="C001")
    def test_save_failure_returns_none(self, mock_id, mock_save, mock_code):
        from backend.commands.contractor.create import create_contractor

        collected = {
            "name_ru": "Test",
            "email": "t@t.t",
            "bank_name": "B",
            "bank_account": "A",
            "address": "A",
            "passport_series": "1",
            "passport_number": "2",
            "inn": "3",
            "bik": "4",
            "corr_account": "5",
        }

        contractor, code = create_contractor(
            collected, ContractorType.SAMOZANYATY, "99", [],
        )

        assert contractor is None
        assert code == ""

    @patch("backend.commands.contractor.create.pop_random_secret_code", return_value="SEC")
    @patch("backend.commands.contractor.create.save_contractor")
    @patch("backend.commands.contractor.create.next_contractor_id", return_value="C010")
    def test_missing_fields_default_to_empty_string(self, mock_id, mock_save, mock_code):
        from backend.commands.contractor.create import create_contractor

        collected = {
            "name_ru": "Test",
            "email": "t@t.t",
            "bank_name": "",
            "bank_account": "",
        }

        contractor, code = create_contractor(
            collected, ContractorType.SAMOZANYATY, "55", [],
        )

        assert contractor is not None
        assert contractor.address == ""
        assert contractor.inn == ""
