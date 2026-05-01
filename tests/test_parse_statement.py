"""Tests for the Bunq statement parser."""

from pathlib import Path
from unittest.mock import MagicMock

from backend.commands.bank.parse_statement import ParseBankStatement

_SAMPLE = Path(__file__).resolve().parent.parent / "docs" / "sample-data" / "bunq-april.csv"


def _run(rate=100.0):
    return ParseBankStatement(MagicMock()).execute(_SAMPLE, rate, upload=False)


def test_skips_income_rows():
    expenses = _run()
    # Sample has 14 positive (Stripe + iDEAL Top Up) and 21 negative rows
    assert len(expenses) == 20  # one negative row triggers a 50/50 split
    assert all("STRIPE" not in e.contractor.upper() for e in expenses)
    assert all("ADYEN" not in e.contractor.upper() for e in expenses)


def test_all_rows_use_default_entity():
    assert {e.entity for e in _run()} == {"republic-nl"}


def test_owner_transfer_classified_as_manager_withdrawal():
    luka_rows = [e for e in _run() if e.contractor == "Luka Asfari"]
    assert len(luka_rows) == 2
    assert all(r.group == "managers" for r in luka_rows)
    assert all(r.description == "Зп + амазон + авторы" for r in luka_rows)


def test_bunq_bv_classified_as_banking():
    bunq_rows = [e for e in _run() if e.contractor == "bunq"]
    assert len(bunq_rows) == 1
    assert bunq_rows[0].group == "banking"


def test_known_service_match_uses_service_map():
    sentry_rows = [e for e in _run() if e.contractor == "Sentry"]
    assert len(sentry_rows) == 1
    assert sentry_rows[0].group == "infrastructure"
    assert sentry_rows[0].comment == ""


def test_unknown_card_payment_splits_with_review_flag():
    streamyard_rows = [e for e in _run() if e.contractor == "STREAMYARD.COM"]
    assert len(streamyard_rows) == 2  # 50/50 split between two units
    assert all(r.comment == "NEEDS REVIEW" for r in streamyard_rows)
    assert {r.unit for r in streamyard_rows} == {"backoffice republic", "backoffice spletnik"}


def test_unknown_person_defaults_to_author():
    ilia = [e for e in _run() if e.contractor == "Ilia Venyavkin"]
    assert len(ilia) == 1
    assert ilia[0].group == "authors"
    assert ilia[0].description == "Гонорар автора"


def test_eur_amount_converts_with_rate():
    expenses = _run(rate=100.0)
    # Line 6: -103,99 EUR -> 10399.00 RUB at rate 100
    ilia = next(e for e in expenses if e.contractor == "Ilia Venyavkin")
    assert ilia.amount_rub == 10399.00


def test_upload_invoked_when_flag_set():
    gw = MagicMock()
    ParseBankStatement(gw).execute(_SAMPLE, 100.0, upload=True)
    gw.upload_expenses.assert_called_once()
