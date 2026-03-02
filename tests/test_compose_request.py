"""Tests for backend/domain/compose_request.py — prompt assembly."""

import pytest

from backend.domain.compose_request import (
    _MODELS,
    contractor_parse,
    editorial_assess,
    inbox_classify,
    support_email,
    support_email_with_context,
    support_triage,
    tech_search_terms,
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
            "editorial_assess",
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
        prompt, model, keys = support_email_with_context("test email", "user data")
        assert isinstance(prompt, str)
        assert model == _MODELS["support_email"]
        assert keys == ["reply"]

    def test_tech_search_terms_returns_tuple(self):
        prompt, model, keys = tech_search_terms("test email")
        assert isinstance(prompt, str)
        assert model == _MODELS["tech_search_terms"]
        assert keys == ["search_terms", "needs_code"]

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
        prompt, _, _ = support_email_with_context("email text", "## User Info\n- ID: 123")
        assert "## User Info" in prompt

    def test_translate_name_contains_name(self):
        prompt, _, _ = translate_name("Jean-Pierre Dupont")
        assert "Jean-Pierre Dupont" in prompt

    def test_support_triage_contains_email(self):
        prompt, _, _ = support_triage("The user has billing issues")
        assert "The user has billing issues" in prompt
