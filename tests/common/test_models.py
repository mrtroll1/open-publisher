import pytest

from common.models import (
    Contractor,
    FieldMeta,
    GlobalContractor,
    IncomingEmail,
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
#  Contractor.required_fields()
# ===================================================================

class TestRequiredFields:

    def test_global_required_fields(self):
        fields = GlobalContractor.required_fields()
        assert "name_en" in fields
        assert "address" in fields
        assert "bank_name" in fields
        assert "bank_account" in fields
        assert "swift" in fields
        # email is not required for global
        assert "email" not in fields

    def test_global_required_fields_labels(self):
        fields = GlobalContractor.required_fields()
        assert fields["name_en"] == "полное имя (латиницей)"
        assert fields["swift"] == "BIC/SWIFT"

    def test_ip_required_fields(self):
        fields = IPContractor.required_fields()
        assert "name_ru" in fields
        assert "ogrnip" in fields
        assert "passport_series" in fields
        assert "passport_number" in fields
        assert "passport_issued_by" in fields
        assert "passport_issued_date" in fields
        assert "passport_code" in fields
        assert "email" in fields
        assert "bank_name" in fields
        assert "bank_account" in fields
        assert "bik" in fields
        assert "corr_account" in fields

    def test_samozanyaty_required_fields(self):
        fields = SamozanyatyContractor.required_fields()
        assert "name_ru" in fields
        assert "inn" in fields
        assert "passport_series" in fields
        assert "passport_number" in fields
        assert "address" in fields
        assert "email" in fields
        assert "bank_name" in fields
        assert "bank_account" in fields
        assert "bik" in fields
        assert "corr_account" in fields

    def test_base_contractor_has_no_fields(self):
        fields = Contractor.required_fields()
        assert fields == {}


# ===================================================================
#  Contractor.all_field_labels()
# ===================================================================

class TestAllFieldLabels:

    def test_global_all_labels(self):
        labels = GlobalContractor.all_field_labels()
        assert "name_en" in labels
        assert "email" in labels
        assert "swift" in labels
        # Should contain all fields from FIELD_META
        assert len(labels) == len(GlobalContractor.FIELD_META)

    def test_ip_all_labels(self):
        labels = IPContractor.all_field_labels()
        assert len(labels) == len(IPContractor.FIELD_META)
        assert "ogrnip" in labels
        assert labels["ogrnip"] == "ОГРНИП"

    def test_samozanyaty_all_labels(self):
        labels = SamozanyatyContractor.all_field_labels()
        assert len(labels) == len(SamozanyatyContractor.FIELD_META)
        assert "inn" in labels
        assert labels["inn"] == "ИНН"

    def test_base_contractor_has_no_labels(self):
        labels = Contractor.all_field_labels()
        assert labels == {}

    def test_labels_are_subset_of_all(self):
        """All required fields should appear in all_field_labels too."""
        required = GlobalContractor.required_fields()
        all_labels = GlobalContractor.all_field_labels()
        for key in required:
            assert key in all_labels


# ===================================================================
#  Contractor.field_names_csv()
# ===================================================================

class TestFieldNamesCsv:

    def test_global_csv(self):
        csv = GlobalContractor.field_names_csv()
        assert "name_en" in csv
        assert "swift" in csv
        # Fields separated by ", "
        parts = csv.split(", ")
        assert len(parts) == len(GlobalContractor.FIELD_META)

    def test_ip_csv(self):
        csv = IPContractor.field_names_csv()
        parts = csv.split(", ")
        assert len(parts) == len(IPContractor.FIELD_META)
        assert "ogrnip" in parts

    def test_samozanyaty_csv(self):
        csv = SamozanyatyContractor.field_names_csv()
        parts = csv.split(", ")
        assert len(parts) == len(SamozanyatyContractor.FIELD_META)
        assert "inn" in parts

    def test_base_contractor_empty_csv(self):
        csv = Contractor.field_names_csv()
        assert csv == ""


# ===================================================================
#  IncomingEmail.as_text()
# ===================================================================

class TestIncomingEmailAsText:

    def test_basic_format(self):
        email = IncomingEmail(
            uid="1",
            from_addr="sender@test.com",
            subject="Hello",
            body="This is the body.",
            date="2025-01-01",
        )
        text = email.as_text()
        assert text == "From: sender@test.com\nSubject: Hello\n\nThis is the body."

    def test_empty_body(self):
        email = IncomingEmail(
            uid="2",
            from_addr="a@b.c",
            subject="No body",
            body="",
            date="2025-01-01",
        )
        text = email.as_text()
        assert text == "From: a@b.c\nSubject: No body\n\n"

    def test_multiline_body(self):
        email = IncomingEmail(
            uid="3",
            from_addr="a@b.c",
            subject="Sub",
            body="Line 1\nLine 2\nLine 3",
            date="2025-01-01",
        )
        text = email.as_text()
        assert "Line 1\nLine 2\nLine 3" in text

    def test_unicode_content(self):
        email = IncomingEmail(
            uid="4",
            from_addr="отправитель@почта.рф",
            subject="Тема",
            body="Текст письма",
            date="2025-01-01",
        )
        text = email.as_text()
        assert "From: отправитель@почта.рф" in text
        assert "Subject: Тема" in text
        assert "Текст письма" in text

    def test_only_includes_from_subject_body(self):
        """to_addr, reply_to, message_id etc. are NOT in as_text output."""
        email = IncomingEmail(
            uid="5",
            from_addr="a@b.c",
            to_addr="x@y.z",
            reply_to="r@t.u",
            subject="Sub",
            body="Body",
            date="2025-01-01",
            message_id="<msg123>",
        )
        text = email.as_text()
        assert "x@y.z" not in text
        assert "r@t.u" not in text
        assert "<msg123>" not in text
