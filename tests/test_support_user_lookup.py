"""Tests for SupportUserLookup static formatters — pure string logic."""

import pytest

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
