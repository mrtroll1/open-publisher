"""Tests for RegistrationParser."""

from unittest.mock import patch

from backend.models import ContractorType


class TestParse:
    @patch("backend.commands.contractor.registration.DbGateway")
    @patch("backend.commands.contractor.registration.KnowledgeRetriever")
    @patch("backend.commands.contractor.registration.GeminiGateway")
    def test_returns_parsed_fields(self, mock_gemini_cls, mock_retriever_cls, mock_db_cls):
        mock_gemini = mock_gemini_cls.return_value
        mock_gemini.call.return_value = {"name": "Иванов Иван", "inn": "123456789012"}
        mock_retriever = mock_retriever_cls.return_value
        mock_retriever.get_domain_context.return_value = ""
        mock_retriever.retrieve_full_domain.return_value = ""
        mock_db = mock_db_cls.return_value
        mock_db.save_message.return_value = "msg-1"

        from backend.commands.contractor.registration import RegistrationParser
        result = RegistrationParser().parse("Иванов Иван ИНН 123456789012", ContractorType.SAMOZANYATY)

        assert result["name"] == "Иванов Иван"
        assert result["inn"] == "123456789012"
        assert result["_validation_id"] == "msg-1"

    @patch("backend.commands.contractor.registration.DbGateway")
    @patch("backend.commands.contractor.registration.KnowledgeRetriever")
    @patch("backend.commands.contractor.registration.GeminiGateway")
    def test_parse_error_returned_as_is(self, mock_gemini_cls, mock_retriever_cls, _db):
        mock_gemini_cls.return_value.call.return_value = {"parse_error": "bad input"}
        mock_retriever_cls.return_value.get_domain_context.return_value = ""
        mock_retriever_cls.return_value.retrieve_full_domain.return_value = ""

        from backend.commands.contractor.registration import RegistrationParser
        result = RegistrationParser().parse("garbage", ContractorType.SAMOZANYATY)

        assert "parse_error" in result
        assert "_validation_id" not in result


class TestTranslateName:
    @patch("backend.commands.contractor.registration.DbGateway")
    @patch("backend.commands.contractor.registration.KnowledgeRetriever")
    @patch("backend.commands.contractor.registration.GeminiGateway")
    def test_returns_translated_name(self, mock_gemini_cls, _retriever, _db):
        mock_gemini_cls.return_value.call.return_value = {"translated_name": "Джон Доу"}

        from backend.commands.contractor.registration import RegistrationParser
        result = RegistrationParser().translate_name("John Doe")

        assert result == "Джон Доу"

    @patch("backend.commands.contractor.registration.DbGateway")
    @patch("backend.commands.contractor.registration.KnowledgeRetriever")
    @patch("backend.commands.contractor.registration.GeminiGateway")
    def test_returns_empty_on_missing_key(self, mock_gemini_cls, _retriever, _db):
        mock_gemini_cls.return_value.call.return_value = {}

        from backend.commands.contractor.registration import RegistrationParser
        result = RegistrationParser().translate_name("Unknown")

        assert result == ""
