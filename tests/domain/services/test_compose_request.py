"""Tests for backend/domain/compose_request.py — prompt assembly."""

import pytest
from unittest.mock import MagicMock, patch

from backend.domain.services.compose_request import (
    _MODELS,
    classify_command,
    contractor_parse,
    conversation_reply,
    editorial_assess,
    inbox_classify,
    support_email,
    support_triage,
    tech_search_terms,
    tech_support_question,
    translate_name,
)


# ===================================================================
#  _MODELS registry
# ===================================================================

class TestModels:

    def test_all_expected_keys_present(self):
        expected = {
            "support_email", "support_triage", "tech_search_terms",
            "contractor_parse", "translate_name", "inbox_classify",
            "editorial_assess", "tech_support_question", "classify_command",
            "classify_teaching", "conversation_reply",
        }
        assert set(_MODELS.keys()) == expected

    def test_all_models_are_strings(self):
        for key, model in _MODELS.items():
            assert isinstance(model, str), f"{key} model is not a string"


# ===================================================================
#  Return structure: (prompt, model, keys)
# ===================================================================

class TestReturnStructure:

    def test_support_triage_returns_tuple(self):
        prompt, model, keys = support_triage("test email")
        assert isinstance(prompt, str)
        assert isinstance(model, str)
        assert isinstance(keys, list)
        assert keys == ["needs", "lookup_email"]

    def test_support_email_returns_tuple(self):
        prompt, model, keys = support_email("test email")
        assert isinstance(prompt, str)
        assert model == _MODELS["support_email"]
        assert keys == ["reply"]

    def test_support_email_with_context_returns_tuple(self):
        prompt, model, keys = support_email("test email", "user data")
        assert isinstance(prompt, str)
        assert model == _MODELS["support_email"]
        assert keys == ["reply"]

    def test_tech_search_terms_returns_tuple(self):
        prompt, model, keys = tech_search_terms("test email")
        assert isinstance(prompt, str)
        assert model == _MODELS["tech_search_terms"]
        assert keys == ["needs_code"]

    def test_translate_name_returns_tuple(self):
        prompt, model, keys = translate_name("John Smith")
        assert isinstance(prompt, str)
        assert model == _MODELS["translate_name"]
        assert keys == ["translated_name"]

    def test_inbox_classify_returns_tuple(self):
        prompt, model, keys = inbox_classify("test email")
        assert isinstance(prompt, str)
        assert model == _MODELS["inbox_classify"]
        assert keys == ["category", "reason"]

    def test_editorial_assess_returns_tuple(self):
        prompt, model, keys = editorial_assess("editorial email")
        assert isinstance(prompt, str)
        assert model == _MODELS["editorial_assess"]
        assert keys == ["forward", "reply"]


# ===================================================================
#  contractor_parse: dynamic key extraction
# ===================================================================

class TestContractorParse:

    def test_keys_from_csv(self):
        _, _, keys = contractor_parse("some text", "name_en, address, email")
        assert keys == ["name_en", "address", "email"]

    def test_single_field(self):
        _, _, keys = contractor_parse("text", "name_ru")
        assert keys == ["name_ru"]

    def test_keys_stripped(self):
        _, _, keys = contractor_parse("text", "  field1  ,  field2  ")
        assert keys == ["field1", "field2"]

    def test_model_correct(self):
        _, model, _ = contractor_parse("text", "name_en")
        assert model == _MODELS["contractor_parse"]

    def test_prompt_contains_input(self):
        prompt, _, _ = contractor_parse("free form text here", "name_en, email")
        assert "free form text here" in prompt

    def test_context_included_when_provided(self):
        prompt, _, _ = contractor_parse("text", "name_en", context="extra context")
        assert "extra context" in prompt


# ===================================================================
#  Prompt content checks
# ===================================================================

class TestPromptContent:

    def test_support_email_contains_email_text(self):
        prompt, _, _ = support_email("Dear support, I have a problem.")
        assert "Dear support, I have a problem." in prompt

    def test_support_email_with_context_contains_user_data(self):
        prompt, _, _ = support_email("email text", "## User Info\n- ID: 123")
        assert "## User Info" in prompt

    def test_translate_name_contains_name(self):
        prompt, _, _ = translate_name("Jean-Pierre Dupont")
        assert "Jean-Pierre Dupont" in prompt

    def test_support_triage_contains_email(self):
        prompt, _, _ = support_triage("The user has billing issues")
        assert "The user has billing issues" in prompt


# ===================================================================
#  tech_support_question()
# ===================================================================

class TestTechSupportQuestion:

    def test_returns_tuple(self):
        prompt, model, keys = tech_support_question("how to deploy?")
        assert isinstance(prompt, str)
        assert isinstance(model, str)
        assert isinstance(keys, list)
        assert keys == ["answer"]

    def test_prompt_contains_question(self):
        prompt, _, _ = tech_support_question("how to restart nginx?")
        assert "how to restart nginx?" in prompt

    def test_verbose_text_included(self):
        prompt_verbose, _, _ = tech_support_question("q", verbose=True)
        assert "развёрнутый" in prompt_verbose

    def test_code_context_included(self):
        prompt, _, _ = tech_support_question("q", code_context="def foo(): pass")
        assert "def foo(): pass" in prompt


# ===================================================================
#  KnowledgeRetriever calls
# ===================================================================

class TestRetrieverCalls:
    """Verify each function calls the retriever with correct arguments."""

    def _make_retriever(self):
        r = MagicMock()
        r.get_domain_context.return_value = "domain-ctx"
        r.retrieve.return_value = "relevant-kb"
        r.retrieve_full_domain.return_value = "full-kb"
        return r

    def test_support_email_calls_domain_context_and_retrieve(self):
        r = self._make_retriever()
        with patch("backend.domain.services.compose_request._get_retriever", return_value=r):
            support_email("my email text")
        r.get_domain_context.assert_called_once_with("tech_support")
        r.retrieve.assert_called_once_with("my email text", "tech_support", 5)

    def test_tech_support_question_calls_domain_context_and_retrieve(self):
        r = self._make_retriever()
        with patch("backend.domain.services.compose_request._get_retriever", return_value=r):
            tech_support_question("how to reset?")
        r.get_domain_context.assert_called_once_with("tech_support")
        r.retrieve.assert_called_once_with("how to reset?", "tech_support", 5)

    def test_support_triage_calls_retrieve_full_domain(self):
        r = self._make_retriever()
        with patch("backend.domain.services.compose_request._get_retriever", return_value=r):
            support_triage("billing issue")
        r.retrieve_full_domain.assert_called_once_with("support_triage")

    def test_contractor_parse_calls_domain_context_and_retrieve_full_domain(self):
        r = self._make_retriever()
        with patch("backend.domain.services.compose_request._get_retriever", return_value=r):
            contractor_parse("text", "name_en")
        r.get_domain_context.assert_called_once_with("contractor")
        r.retrieve_full_domain.assert_called_once_with("contractor")


# ===================================================================
#  conversation_reply()
# ===================================================================

class TestConversationReply:

    def test_returns_correct_structure(self):
        prompt, model, keys = conversation_reply("hi", "prev msgs", "kb")
        assert isinstance(prompt, str)
        assert model == _MODELS["conversation_reply"]
        assert keys == ["reply"]

    def test_verbose_flag_false(self):
        prompt, _, _ = conversation_reply("hi", "", "")
        assert "кратко" in prompt

    def test_verbose_flag_true(self):
        prompt, _, _ = conversation_reply("hi", "", "", verbose=True)
        assert "развёрнутый" in prompt

    def test_prompt_contains_all_placeholders(self):
        prompt, _, _ = conversation_reply(
            "user msg", "history text", "knowledge text", verbose=False,
        )
        assert "user msg" in prompt
        assert "history text" in prompt
        assert "knowledge text" in prompt

    def test_backward_compat_without_environment(self):
        prompt, model, keys = conversation_reply("hi", "hist", "kb")
        assert "(контекст не указан)" in prompt
        assert keys == ["reply"]

    def test_environment_context_included(self):
        prompt, _, _ = conversation_reply(
            "hi", "hist", "kb", environment_context="Ты редактор журнала",
        )
        assert "Ты редактор журнала" in prompt
        assert "(контекст не указан)" not in prompt

    def test_empty_environment_uses_default(self):
        prompt, _, _ = conversation_reply("hi", "hist", "kb", environment_context="")
        assert "(контекст не указан)" in prompt


# ===================================================================
#  _get_retriever() lazy singleton
# ===================================================================

class TestGetRetrieverSingleton:

    @pytest.fixture(autouse=True)
    def _stub_knowledge_retriever(self):
        """Override the conftest autouse fixture — let _get_retriever run for real."""
        yield

    def test_creates_instance_once(self):
        import sys
        import backend.domain.services.compose_request as mod

        original = mod._retriever
        mod._retriever = None
        try:
            instance = MagicMock()
            fake_module = MagicMock()
            fake_module.KnowledgeRetriever.return_value = instance

            with patch.dict(sys.modules, {"backend.domain.services.knowledge_retriever": fake_module}):
                result1 = mod._get_retriever()
                result2 = mod._get_retriever()

                fake_module.KnowledgeRetriever.assert_called_once()
                assert result1 is result2
                assert result1 is instance
        finally:
            mod._retriever = original
