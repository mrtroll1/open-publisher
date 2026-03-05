import pytest

from backend.domain.use_cases.validate_contractor import _digits_only, validate_fields
from common.models import ContractorType


# ===================================================================
#  _digits_only
# ===================================================================

class TestDigitsOnly:

    def test_pure_digits(self):
        assert _digits_only("1234") == "1234"

    def test_mixed(self):
        assert _digits_only("12 34") == "1234"

    def test_non_digits(self):
        assert _digits_only("abc") == ""

    def test_empty(self):
        assert _digits_only("") == ""


# ===================================================================
#  validate_fields — SAMOZANYATY
# ===================================================================

class TestValidateSamozanyaty:

    CTYPE = ContractorType.SAMOZANYATY

    def test_valid_passport_series(self):
        w = validate_fields({"passport_series": "1234"}, self.CTYPE)
        assert not w

    def test_invalid_passport_series(self):
        w = validate_fields({"passport_series": "123"}, self.CTYPE)
        assert len(w) == 1
        assert "4 цифры" in w[0]

    def test_valid_passport_number(self):
        w = validate_fields({"passport_number": "567890"}, self.CTYPE)
        assert not w

    def test_invalid_passport_number(self):
        w = validate_fields({"passport_number": "12345"}, self.CTYPE)
        assert len(w) == 1
        assert "6 цифр" in w[0]

    def test_valid_inn_12(self):
        w = validate_fields({"inn": "123456789012"}, self.CTYPE)
        assert not w

    def test_valid_inn_10(self):
        w = validate_fields({"inn": "1234567890"}, self.CTYPE)
        assert not w

    def test_invalid_inn_11(self):
        w = validate_fields({"inn": "12345678901"}, self.CTYPE)
        assert len(w) == 1
        assert "ИНН" in w[0]

    def test_valid_bank_account(self):
        w = validate_fields({"bank_account": "40817810099910004312"}, self.CTYPE)
        assert not w

    def test_invalid_bank_account(self):
        w = validate_fields({"bank_account": "12345"}, self.CTYPE)
        assert len(w) == 1
        assert "20 цифр" in w[0]

    def test_valid_bik(self):
        w = validate_fields({"bik": "044525225"}, self.CTYPE)
        assert not w

    def test_invalid_bik(self):
        w = validate_fields({"bik": "12345"}, self.CTYPE)
        assert len(w) == 1
        assert "БИК" in w[0]

    def test_valid_corr_account(self):
        w = validate_fields({"corr_account": "30101810400000000225"}, self.CTYPE)
        assert not w

    def test_invalid_corr_account(self):
        w = validate_fields({"corr_account": "123"}, self.CTYPE)
        assert len(w) == 1
        assert "Корр" in w[0]

    def test_valid_passport_code_with_dash(self):
        w = validate_fields({"passport_code": "123-456"}, self.CTYPE)
        assert not w

    def test_valid_passport_code_without_dash(self):
        w = validate_fields({"passport_code": "123456"}, self.CTYPE)
        assert not w

    def test_invalid_passport_code(self):
        w = validate_fields({"passport_code": "12345"}, self.CTYPE)
        assert len(w) == 1
        assert "NNN-NNN" in w[0]

    def test_valid_address(self):
        w = validate_fields(
            {"address": "123456, г. Москва, ул. Ленина, д. 1, кв. 5"}, self.CTYPE,
        )
        assert not w

    def test_address_missing_index(self):
        w = validate_fields(
            {"address": "г. Москва, ул. Ленина, д. 1, кв. 5"}, self.CTYPE,
        )
        assert len(w) == 1
        assert "почтовый индекс" in w[0]

    def test_valid_email(self):
        w = validate_fields({"email": "user@example.com"}, self.CTYPE)
        assert not w

    def test_invalid_email(self):
        w = validate_fields({"email": "not-an-email"}, self.CTYPE)
        assert len(w) == 1
        assert "email" in w[0].lower()

    def test_empty_fields_no_warnings(self):
        w = validate_fields({}, self.CTYPE)
        assert w == []

    def test_all_valid_fields(self):
        w = validate_fields({
            "passport_series": "1234",
            "passport_number": "567890",
            "inn": "123456789012",
            "bank_account": "40817810099910004312",
            "bik": "044525225",
            "corr_account": "30101810400000000225",
            "passport_code": "123-456",
            "address": "123456, г. Москва, ул. Ленина, д. 1, кв. 5",
            "email": "user@example.com",
        }, self.CTYPE)
        assert w == []


# ===================================================================
#  validate_fields — IP
# ===================================================================

class TestValidateIP:

    CTYPE = ContractorType.IP

    def test_valid_ogrnip(self):
        w = validate_fields({"ogrnip": "315774600000000"}, self.CTYPE)
        assert not w

    def test_invalid_ogrnip(self):
        w = validate_fields({"ogrnip": "31577460000000"}, self.CTYPE)
        assert len(w) == 1
        assert "ОГРНИП" in w[0]

    def test_passport_validation_same_as_samoz(self):
        w = validate_fields({"passport_series": "123"}, self.CTYPE)
        assert len(w) == 1
        assert "4 цифры" in w[0]

    def test_inn_validation_same_as_samoz(self):
        w = validate_fields({"inn": "12345678901"}, self.CTYPE)
        assert len(w) == 1
        assert "ИНН" in w[0]


# ===================================================================
#  validate_fields — GLOBAL
# ===================================================================

class TestValidateGlobal:

    CTYPE = ContractorType.GLOBAL

    def test_valid_swift_8(self):
        w = validate_fields({"swift": "DEUTDEFF"}, self.CTYPE)
        assert not w

    def test_valid_swift_11(self):
        w = validate_fields({"swift": "DEUTDEFFXXX"}, self.CTYPE)
        assert not w

    def test_invalid_swift(self):
        w = validate_fields({"swift": "SHORT"}, self.CTYPE)
        assert len(w) == 1
        assert "SWIFT" in w[0]

    def test_valid_iban(self):
        w = validate_fields({"bank_account": "DE89370400440532013000"}, self.CTYPE)
        assert not w

    def test_invalid_iban(self):
        w = validate_fields({"bank_account": "DE!!"}, self.CTYPE)
        assert len(w) == 1
        assert "IBAN" in w[0]

    def test_non_iban_account_no_iban_warning(self):
        w = validate_fields({"bank_account": "1234567890"}, self.CTYPE)
        assert not w

    def test_cyrillic_address(self):
        w = validate_fields({"address": "Москва, ул. Ленина"}, self.CTYPE)
        assert len(w) == 1
        assert "латиницей" in w[0]

    def test_latin_address(self):
        w = validate_fields({"address": "123 Main St, Berlin"}, self.CTYPE)
        assert not w

    def test_valid_email(self):
        w = validate_fields({"email": "user@example.com"}, self.CTYPE)
        assert not w

    def test_invalid_email(self):
        w = validate_fields({"email": "bad"}, self.CTYPE)
        assert len(w) == 1
        assert "email" in w[0].lower()

    def test_no_passport_inn_validation(self):
        w = validate_fields({
            "passport_series": "1",
            "inn": "1",
            "bik": "1",
        }, self.CTYPE)
        assert w == []

    def test_empty_fields_no_warnings(self):
        w = validate_fields({}, self.CTYPE)
        assert w == []
