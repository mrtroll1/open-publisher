"""Tests for common/prompt_loader.py — template loading."""

import pytest

from common.prompt_loader import load_template


# ===================================================================
#  load_template()
# ===================================================================

class TestLoadTemplate:

    def test_loads_existing_template(self):
        # translate-name.md is a known small template
        text = load_template("contractor/translate-name.md")
        assert "{{NAME}}" in text or "translated_name" in text

    def test_replacement_applied(self):
        text = load_template("contractor/translate-name.md", {"NAME": "John Smith"})
        assert "John Smith" in text
        assert "{{NAME}}" not in text

    def test_multiple_replacements(self):
        text = load_template("email/support-email.md", {
            "KNOWLEDGE": "TEST_KNOWLEDGE",
            "USER_DATA": "TEST_USER_DATA",
            "EMAIL": "TEST_EMAIL",
        })
        assert "TEST_KNOWLEDGE" in text
        assert "TEST_EMAIL" in text

    def test_no_replacements_leaves_placeholders(self):
        text = load_template("contractor/translate-name.md")
        assert "{{NAME}}" in text

    def test_empty_replacements_dict(self):
        text = load_template("contractor/translate-name.md", {})
        assert "{{NAME}}" in text

    def test_nonexistent_template_raises(self):
        with pytest.raises(FileNotFoundError):
            load_template("nonexistent-template-xyz.md")
