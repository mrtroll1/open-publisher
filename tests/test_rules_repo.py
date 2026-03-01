"""Tests for rules_repo data classes — pure construction logic."""

import pytest

from backend.infrastructure.repositories.rules_repo import (
    ArticleRateRule,
    FlatRateRule,
    RedirectRule,
)


# ===================================================================
#  RedirectRule
# ===================================================================

class TestRedirectRule:

    def test_basic_construction(self):
        r = RedirectRule(source_name="Author A", target_id="C001", add_to_total=True)
        assert r.source_name == "Author A"
        assert r.target_id == "C001"
        assert r.add_to_total is True

    def test_empty_target_means_exclusion(self):
        r = RedirectRule(source_name="Excluded", target_id="", add_to_total=False)
        assert r.target_id == ""
        assert r.add_to_total is False


# ===================================================================
#  FlatRateRule
# ===================================================================

class TestFlatRateRule:

    def test_basic_construction(self):
        r = FlatRateRule(
            contractor_id="C001", name="AFP", label="Агентство",
            eur=100, rub=10000,
        )
        assert r.contractor_id == "C001"
        assert r.name == "AFP"
        assert r.label == "Агентство"
        assert r.eur == 100
        assert r.rub == 10000

    def test_empty_contractor_id(self):
        r = FlatRateRule(
            contractor_id="", name="Service", label="SRV",
            eur=50, rub=5000,
        )
        assert r.contractor_id == ""


# ===================================================================
#  ArticleRateRule
# ===================================================================

class TestArticleRateRule:

    def test_basic_construction(self):
        r = ArticleRateRule(contractor_id="C002", eur=200, rub=20000)
        assert r.contractor_id == "C002"
        assert r.eur == 200
        assert r.rub == 20000

    def test_zero_rates(self):
        r = ArticleRateRule(contractor_id="C003", eur=0, rub=0)
        assert r.eur == 0
        assert r.rub == 0
