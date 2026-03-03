"""Fetch and format user data from Republic + Redefine for support drafts."""

from __future__ import annotations

import logging

from backend.infrastructure.gateways.redefine_gateway import RedefineGateway
from backend.infrastructure.gateways.republic_gateway import RepublicGateway

logger = logging.getLogger(__name__)


class SupportUserLookup:
    def __init__(self):
        self._republic = RepublicGateway()
        self._redefine = RedefineGateway()

    def fetch_and_format(self, email: str, needs: list[str]) -> str:
        """Fetch requested data categories and return formatted Russian text."""
        sections: list[str] = []

        republic_user = self._republic.get_user_by_email(email)
        logger.info("Republic lookup for %s: %s", email, "found" if republic_user else "not found")

        redefine_customer = self._redefine.get_customer_by_email(email)
        logger.info("Redefine lookup for %s: %s", email, "found" if redefine_customer else "not found")

        # Fallback: use redefine_user_id from Republic if direct lookup failed
        if not redefine_customer and republic_user:
            rid = republic_user.get("redefine_user_id")
            if rid:
                redefine_customer = {"id": rid, "_fallback": True}

        customer_id = redefine_customer.get("id") if redefine_customer else None

        if "account_info" in needs:
            sections.append(self._fmt_account(republic_user, redefine_customer, email))

        subscriptions = []
        if customer_id and ("subscription_info" in needs or "payments_info" in needs):
            subscriptions = self._redefine.get_subscriptions(customer_id)

        if "subscription_info" in needs:
            sections.append(self._fmt_subscriptions(subscriptions))

        if "payments_info" in needs:
            payment_methods = self._redefine.get_payment_methods(customer_id) if customer_id else []
            transactions = []
            for sub in subscriptions:
                transactions.extend(self._redefine.get_transactions(sub["id"]))
            sections.append(self._fmt_payments(payment_methods, transactions))

        if "audit_log" in needs and customer_id:
            log = self._redefine.get_audit_log(customer_id, email)
            sections.append(self._fmt_audit_log(log))

        return "\n\n".join(sections)


    @staticmethod
    def _fmt_account(republic: dict | None, redefine: dict | None, email: str) -> str:
        lines = [f"## Аккаунт ({email})"]
        if not republic and not redefine:
            lines.append("Аккаунт не найден ни в Republic, ни в Redefine.")
            return "\n".join(lines)
        if republic:
            lines.append(f"- Republic ID: {republic['id']}")
            name = f"{republic.get('first_name', '')} {republic.get('last_name', '')}".strip()
            if name:
                lines.append(f"- Имя: {name}")
            lines.append(f"- Email подтверждён: {'да' if republic.get('email_confirmed') else 'нет'}")
            lines.append(f"- Регистрация: {republic.get('signed_up_at', '—')}")
            lines.append(f"- Последний вход: {republic.get('last_signed_in_at', '—')}")
            if republic.get("ban") or republic.get("full_ban"):
                lines.append("- ЗАБЛОКИРОВАН")
        if redefine and not redefine.get("_fallback"):
            lines.append(f"- Redefine ID: {redefine['id']}")
        return "\n".join(lines)

    @staticmethod
    def _fmt_subscriptions(subs: list[dict]) -> str:
        lines = ["## Подписки"]
        if not subs:
            lines.append("Подписок не найдено.")
            return "\n".join(lines)
        for s in subs:
            status = s.get("status", "?")
            stype = s.get("type", "?")
            auto = "да" if s.get("auto_renewal") else "нет"
            lines.append(
                f"- {stype} | статус: {status} | автопродление: {auto} "
                f"| {s.get('start_date', '?')} → {s.get('end_date', '?')} "
                f"| валюта: {s.get('currency', '?')}"
            )
        return "\n".join(lines)

    @staticmethod
    def _fmt_payments(methods: list[dict], transactions: list[dict]) -> str:
        lines = ["## Платежи"]
        if methods:
            lines.append("Способы оплаты:")
            for m in methods:
                lines.append(f"- {m.get('kind', '?')} {m.get('masked_number', '?')} | статус: {m.get('status', '?')}")
        if transactions:
            lines.append("Транзакции:")
            for t in transactions:
                lines.append(
                    f"- {t.get('created_at', '?')} | {t.get('currency_amount', '?')} {t.get('currency', '')} "
                    f"| статус: {t.get('status', '?')} | тип: {t.get('type', '?')}"
                )
        if not methods and not transactions:
            lines.append("Данных о платежах не найдено.")
        return "\n".join(lines)

    @staticmethod
    def _fmt_audit_log(log: list[dict]) -> str:
        lines = ["## Лог действий"]
        if not log:
            lines.append("Записей не найдено.")
            return "\n".join(lines)
        for entry in log[:20]:  # cap for prompt size
            lines.append(
                f"- {entry.get('created_at', '?')} | {entry.get('action', '?')} "
                f"| статус: {entry.get('status', '?')}"
            )
        if len(log) > 20:
            lines.append(f"... и ещё {len(log) - 20} записей")
        return "\n".join(lines)
