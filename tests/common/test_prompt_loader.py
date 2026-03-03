"""Tests for common/prompt_loader.py — template and knowledge loading."""

import pytest

from common.prompt_loader import load_template, load_knowledge, _TEMPLATES, _KNOWLEDGE


# ===================================================================
#  load_template()
# ===================================================================

class TestLoadTemplate:

    def test_loads_existing_template(self):
        # translate-name.md is a known small template
        text = load_template("translate-name.md")
        assert "{{NAME}}" in text or "translated_name" in text

    def test_replacement_applied(self):
        text = load_template("translate-name.md", {"NAME": "John Smith"})
        assert "John Smith" in text
        assert "{{NAME}}" not in text

    def test_multiple_replacements(self):
        text = load_template("support-email.md", {
            "KNOWLEDGE": "TEST_KNOWLEDGE",
            "USER_DATA": "TEST_USER_DATA",
            "EMAIL": "TEST_EMAIL",
        })
        assert "TEST_KNOWLEDGE" in text
        assert "TEST_EMAIL" in text

    def test_no_replacements_leaves_placeholders(self):
        text = load_template("translate-name.md")
        assert "{{NAME}}" in text

    def test_empty_replacements_dict(self):
        text = load_template("translate-name.md", {})
        assert "{{NAME}}" in text

    def test_nonexistent_template_raises(self):
        with pytest.raises(FileNotFoundError):
            load_template("nonexistent-template-xyz.md")


# ===================================================================
#  load_knowledge()
# ===================================================================

class TestLoadKnowledge:

    def test_loads_single_file(self):
        text = load_knowledge("base.md")
        assert len(text) > 0

    def test_loads_multiple_files_joined(self):
        text = load_knowledge("base.md", "email-inbox.md")
        # Multiple files are joined with separator
        assert "---" in text

    def test_missing_file_skipped(self):
        # Should not raise for missing files
        text = load_knowledge("base.md", "nonexistent-file-xyz.md")
        assert len(text) > 0

    def test_all_missing_files_returns_empty(self):
        text = load_knowledge("nonexistent1.md", "nonexistent2.md")
        assert text == ""

    def test_no_files_returns_empty(self):
        text = load_knowledge()
        assert text == ""

    def test_replacement_in_knowledge(self):
        text = load_knowledge(
            "tech-support.md",
            replacements={"SUBSCRIPTION_SERVICE_URL": "https://test.example.com"},
        )
        assert "https://test.example.com" in text

    def test_empty_replacements_dict(self):
        text = load_knowledge("base.md", replacements={})
        assert len(text) > 0
