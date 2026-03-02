"""Tests for SupportUserLookup: static formatters + fetch_and_format integration."""

import pytest
from unittest.mock import patch

from backend.domain.support_user_lookup import SupportUserLookup


# ===================================================================
#  _fmt_account()
# ===================================================================

class TestFmtAccount:

    def test_both_missing(self):
        result = SupportUserLookup._fmt_account(None, None, "test@test.com")
        assert "test@test.com" in result
        assert "не найден" in result

    def test_republic_only(self):
        republic = {
            "id": 42,
            "first_name": "Иван",
            "last_name": "Петров",
            "email_confirmed": True,
            "signed_up_at": "2020-01-15",
            "last_signed_in_at": "2026-01-01",
        }
        result = SupportUserLookup._fmt_account(republic, None, "ivan@test.com")
        assert "Republic ID: 42" in result
        assert "Иван Петров" in result
        assert "да" in result
        assert "2020-01-15" in result

    def test_redefine_id_shown(self):
        republic = {"id": 1}
        redefine = {"id": "rdef-99"}
        result = SupportUserLookup._fmt_account(republic, redefine, "a@b.c")
        assert "Redefine ID: rdef-99" in result

    def test_redefine_fallback_hidden(self):
        republic = {"id": 1}
        redefine = {"id": "rdef-99", "_fallback": True}
        result = SupportUserLookup._fmt_account(republic, redefine, "a@b.c")
        assert "Redefine ID" not in result

    def test_banned_user(self):
        republic = {"id": 1, "ban": True}
        result = SupportUserLookup._fmt_account(republic, None, "a@b.c")
        assert "ЗАБЛОКИРОВАН" in result

    def test_full_ban_shown(self):
        republic = {"id": 1, "full_ban": True}
        result = SupportUserLookup._fmt_account(republic, None, "a@b.c")
        assert "ЗАБЛОКИРОВАН" in result

    def test_email_not_confirmed(self):
        republic = {"id": 1, "email_confirmed": False}
        result = SupportUserLookup._fmt_account(republic, None, "a@b.c")
        assert "нет" in result

    def test_no_name(self):
        republic = {"id": 1}
        result = SupportUserLookup._fmt_account(republic, None, "a@b.c")
        assert "Имя:" not in result

    def test_header_contains_email(self):
        result = SupportUserLookup._fmt_account(None, None, "unique@mail.com")
        assert "unique@mail.com" in result


# ===================================================================
#  _fmt_subscriptions()
# ===================================================================

class TestFmtSubscriptions:

    def test_empty_list(self):
        result = SupportUserLookup._fmt_subscriptions([])
        assert "Подписок не найдено" in result

    def test_single_subscription(self):
        subs = [{
            "status": "active",
            "type": "premium",
            "auto_renewal": True,
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "currency": "RUB",
        }]
        result = SupportUserLookup._fmt_subscriptions(subs)
        assert "premium" in result
        assert "active" in result
        assert "да" in result
        assert "RUB" in result
        assert "2026-01-01" in result
        assert "2026-12-31" in result

    def test_auto_renewal_no(self):
        subs = [{"status": "active", "type": "basic", "auto_renewal": False}]
        result = SupportUserLookup._fmt_subscriptions(subs)
        assert "нет" in result

    def test_multiple_subscriptions(self):
        subs = [
            {"status": "active", "type": "a"},
            {"status": "expired", "type": "b"},
        ]
        result = SupportUserLookup._fmt_subscriptions(subs)
        assert "active" in result
        assert "expired" in result

    def test_header_present(self):
        result = SupportUserLookup._fmt_subscriptions([])
        assert "## Подписки" in result


# ===================================================================
#  _fmt_payments()
# ===================================================================

class TestFmtPayments:

    def test_no_methods_no_transactions(self):
        result = SupportUserLookup._fmt_payments([], [])
        assert "Данных о платежах не найдено" in result

    def test_with_payment_methods(self):
        methods = [{"kind": "card", "masked_number": "****1234", "status": "active"}]
        result = SupportUserLookup._fmt_payments(methods, [])
        assert "card" in result
        assert "****1234" in result
        assert "active" in result
        assert "Способы оплаты:" in result

    def test_with_transactions(self):
        txns = [{
            "created_at": "2026-01-15",
            "currency_amount": "500",
            "currency": "RUB",
            "status": "succeeded",
            "type": "payment",
        }]
        result = SupportUserLookup._fmt_payments([], txns)
        assert "500" in result
        assert "RUB" in result
        assert "succeeded" in result
        assert "Транзакции:" in result

    def test_header_present(self):
        result = SupportUserLookup._fmt_payments([], [])
        assert "## Платежи" in result


# ===================================================================
#  _fmt_audit_log()
# ===================================================================

class TestFmtAuditLog:

    def test_empty_log(self):
        result = SupportUserLookup._fmt_audit_log([])
        assert "Записей не найдено" in result

    def test_single_entry(self):
        log = [{"created_at": "2026-01-15", "action": "login", "status": "success"}]
        result = SupportUserLookup._fmt_audit_log(log)
        assert "2026-01-15" in result
        assert "login" in result
        assert "success" in result

    def test_caps_at_20_entries(self):
        log = [{"created_at": f"2026-01-{i:02d}", "action": "act", "status": "ok"} for i in range(1, 30)]
        result = SupportUserLookup._fmt_audit_log(log)
        assert "ещё 9 записей" in result

    def test_exactly_20_entries_no_ellipsis(self):
        log = [{"created_at": f"2026-01-{i:02d}", "action": "act", "status": "ok"} for i in range(1, 21)]
        result = SupportUserLookup._fmt_audit_log(log)
        assert "ещё" not in result

    def test_header_present(self):
        result = SupportUserLookup._fmt_audit_log([])
        assert "## Лог действий" in result


# ===================================================================
#  Helpers for fetch_and_format tests
# ===================================================================

@patch("backend.domain.support_user_lookup.RedefineGateway")
@patch("backend.domain.support_user_lookup.RepublicGateway")
def _make_lookup(MockRepublic, MockRedefine):
    lookup = SupportUserLookup()
    return lookup, lookup._republic, lookup._redefine


# ===================================================================
#  fetch_and_format() — integration tests with mocked gateways
# ===================================================================

class TestFetchAndFormat:

    def test_subscription_info_calls_redefine_and_formats(self):
        lookup, mock_republic, mock_redefine = _make_lookup()
        mock_republic.get_user_by_email.return_value = {"id": 1}
        mock_redefine.get_customer_by_email.return_value = {"id": "cust-1"}
        mock_redefine.get_subscriptions.return_value = [
            {"status": "active", "type": "premium", "auto_renewal": True,
             "start_date": "2026-01-01", "end_date": "2026-12-31", "currency": "RUB"},
        ]

        result = lookup.fetch_and_format("user@test.com", ["subscription_info"])

        assert "## Подписки" in result
        assert "premium" in result
        assert "active" in result
        mock_redefine.get_subscriptions.assert_called_once_with("cust-1")

    def test_payments_info_calls_redefine_and_formats(self):
        lookup, mock_republic, mock_redefine = _make_lookup()
        mock_republic.get_user_by_email.return_value = {"id": 1}
        mock_redefine.get_customer_by_email.return_value = {"id": "cust-2"}
        mock_redefine.get_subscriptions.return_value = [
            {"id": "sub-1", "status": "active", "type": "basic"},
        ]
        mock_redefine.get_payment_methods.return_value = [
            {"kind": "card", "masked_number": "****5678", "status": "active"},
        ]
        mock_redefine.get_transactions.return_value = [
            {"created_at": "2026-02-01", "currency_amount": "1000", "currency": "RUB",
             "status": "succeeded", "type": "payment"},
        ]

        result = lookup.fetch_and_format("user@test.com", ["payments_info"])

        assert "## Платежи" in result
        assert "****5678" in result
        assert "1000" in result
        mock_redefine.get_payment_methods.assert_called_once_with("cust-2")
        mock_redefine.get_transactions.assert_called_once_with("sub-1")

    def test_account_info_calls_republic_and_formats(self):
        lookup, mock_republic, mock_redefine = _make_lookup()
        mock_republic.get_user_by_email.return_value = {
            "id": 42, "first_name": "Иван", "last_name": "Петров",
            "email_confirmed": True, "signed_up_at": "2020-01-15",
            "last_signed_in_at": "2026-01-01",
        }
        mock_redefine.get_customer_by_email.return_value = {"id": "rdef-42"}

        result = lookup.fetch_and_format("ivan@test.com", ["account_info"])

        assert "## Аккаунт" in result
        assert "Republic ID: 42" in result
        assert "Иван Петров" in result
        assert "Redefine ID: rdef-42" in result
        mock_republic.get_user_by_email.assert_called_once_with("ivan@test.com")

    def test_multiple_needs_includes_all_sections(self):
        lookup, mock_republic, mock_redefine = _make_lookup()
        mock_republic.get_user_by_email.return_value = {"id": 10}
        mock_redefine.get_customer_by_email.return_value = {"id": "cust-10"}
        mock_redefine.get_subscriptions.return_value = [
            {"id": "sub-x", "status": "active", "type": "premium"},
        ]
        mock_redefine.get_payment_methods.return_value = []
        mock_redefine.get_transactions.return_value = []

        result = lookup.fetch_and_format(
            "multi@test.com", ["account_info", "subscription_info", "payments_info"],
        )

        assert "## Аккаунт" in result
        assert "## Подписки" in result
        assert "## Платежи" in result

    def test_redefine_customer_lookup_used(self):
        lookup, mock_republic, mock_redefine = _make_lookup()
        mock_republic.get_user_by_email.return_value = None
        mock_redefine.get_customer_by_email.return_value = {"id": "rdef-direct"}
        mock_redefine.get_subscriptions.return_value = []

        result = lookup.fetch_and_format("rdef@test.com", ["subscription_info"])

        assert "## Подписки" in result
        mock_redefine.get_customer_by_email.assert_called_once_with("rdef@test.com")
        mock_redefine.get_subscriptions.assert_called_once_with("rdef-direct")

    def test_handles_gateway_exception_gracefully(self):
        lookup, mock_republic, mock_redefine = _make_lookup()
        mock_republic.get_user_by_email.side_effect = RuntimeError("API down")

        with pytest.raises(RuntimeError):
            lookup.fetch_and_format("error@test.com", ["account_info"])

    def test_empty_needs_returns_empty_string(self):
        lookup, mock_republic, mock_redefine = _make_lookup()
        mock_republic.get_user_by_email.return_value = None
        mock_redefine.get_customer_by_email.return_value = None

        result = lookup.fetch_and_format("nobody@test.com", [])

        assert result == ""

    def test_fallback_redefine_id_from_republic(self):
        lookup, mock_republic, mock_redefine = _make_lookup()
        mock_republic.get_user_by_email.return_value = {
            "id": 5, "redefine_user_id": "rdef-fallback",
        }
        mock_redefine.get_customer_by_email.return_value = None
        mock_redefine.get_subscriptions.return_value = [
            {"id": "sub-fb", "status": "active", "type": "trial"},
        ]

        result = lookup.fetch_and_format("fb@test.com", ["subscription_info"])

        assert "## Подписки" in result
        assert "trial" in result
        # Should use the fallback customer_id from Republic
        mock_redefine.get_subscriptions.assert_called_once_with("rdef-fallback")

    def test_audit_log_fetched_when_customer_exists(self):
        lookup, mock_republic, mock_redefine = _make_lookup()
        mock_republic.get_user_by_email.return_value = {"id": 1}
        mock_redefine.get_customer_by_email.return_value = {"id": "cust-audit"}
        mock_redefine.get_audit_log.return_value = [
            {"created_at": "2026-02-15", "action": "password_change", "status": "success"},
        ]

        result = lookup.fetch_and_format("audit@test.com", ["audit_log"])

        assert "## Лог действий" in result
        assert "password_change" in result
        mock_redefine.get_audit_log.assert_called_once_with("cust-audit", "audit@test.com")
