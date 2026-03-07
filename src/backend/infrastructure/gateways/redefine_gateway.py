"""Redefine API gateway — customer/subscription/payment lookup for support."""

from __future__ import annotations

import logging
from typing import ClassVar
from urllib.parse import quote

import requests

from backend.config import (
    REDEFINE_API_URL,
    REDEFINE_SUPPORT_API_KEY,
)

logger = logging.getLogger(__name__)

_BASE = f"{REDEFINE_API_URL}/s2s/support"


class RedefineGateway:
    """Read-only access to Redefine support endpoints."""

    _headers: ClassVar[dict[str, str]] = {"X-Api-Key": REDEFINE_SUPPORT_API_KEY}

    def get_customer_by_email(self, email: str) -> dict | None:
        """Look up a Redefine customer by email."""
        resp = requests.get(
            f"{_BASE}/customer-by-email/{quote(email, safe='')}",
            headers=self._headers,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("data", {}).get("customer")

    def get_subscriptions(self, customer_id: str) -> list[dict]:
        return self._get_list(f"customer/{customer_id}/subscriptions", "subscriptions")

    def get_payment_methods(self, customer_id: str) -> list[dict]:
        return self._get_list(f"customer/{customer_id}/payment-methods", "payment_methods")

    def get_transactions(self, subscription_id: str) -> list[dict]:
        return self._get_list(f"subscription/{subscription_id}/transactions", "transactions")

    def get_audit_log(self, customer_id: str, email: str) -> list[dict]:
        resp = requests.get(
            f"{_BASE}/customer/{customer_id}/audit-log",
            params={"email": email},
            headers=self._headers,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("data", {}).get("audit_log", [])

    def _get_list(self, path: str, key: str) -> list[dict]:
        """GET a list endpoint, unwrap {"data": {key: [...]}}."""
        resp = requests.get(
            f"{_BASE}/{path}",
            headers=self._headers,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("data", {}).get(key, [])

    def get_pnl_stats(self, month: str) -> dict:
        if not REDEFINE_API_URL:
            raise RuntimeError("REDEFINE_API_URL not configured")
        resp = requests.post(
            f"{REDEFINE_API_URL}/s2s/pnl-by-month",
            json={"month": month},
            headers=self._headers,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("data", {})
