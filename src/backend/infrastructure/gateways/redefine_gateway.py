"""Redefine API gateway — customer/subscription/payment lookup for support."""

from __future__ import annotations

import logging
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

    _headers = {"X-Api-Key": REDEFINE_SUPPORT_API_KEY}

    def get_customer_by_email(self, email: str) -> dict | None:
        """Look up a Redefine customer by email."""
        try:
            resp = requests.get(
                f"{_BASE}/customer-by-email/{quote(email, safe='')}",
                headers=self._headers,
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json().get("data", {}).get("customer")
        except Exception as e:
            logger.error("Redefine customer lookup failed for %s: %s", email, e)
            return None

    def get_subscriptions(self, customer_id: str) -> list[dict]:
        return self._get_list(f"customer/{customer_id}/subscriptions", "subscriptions")

    def get_payment_methods(self, customer_id: str) -> list[dict]:
        return self._get_list(f"customer/{customer_id}/payment-methods", "payment_methods")

    def get_transactions(self, subscription_id: str) -> list[dict]:
        return self._get_list(f"subscription/{subscription_id}/transactions", "transactions")

    def get_audit_log(self, customer_id: str, email: str) -> list[dict]:
        try:
            resp = requests.get(
                f"{_BASE}/customer/{customer_id}/audit-log",
                params={"email": email},
                headers=self._headers,
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json().get("data", {}).get("audit_log", [])
        except Exception as e:
            logger.error("Redefine audit log failed for %s: %s", customer_id, e)
            return []

    def _get_list(self, path: str, key: str) -> list[dict]:
        """GET a list endpoint, unwrap {"data": {key: [...]}}."""
        try:
            resp = requests.get(
                f"{_BASE}/{path}",
                headers=self._headers,
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json().get("data", {}).get(key, [])
        except Exception as e:
            logger.error("Redefine %s failed: %s", path, e)
            return []

    def get_pnl_stats(self, month: str) -> dict:
        if not REDEFINE_API_URL:
            logger.warning("REDEFINE_API_URL not configured")
            return {}
        try:
            resp = requests.post(
                f"{REDEFINE_API_URL}/s2s/pnl-by-month",
                json={"month": month},
                headers=self._headers,
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json().get("data", {})
        except Exception as e:
            logger.error("PNL stats fetch failed for %s: %s", month, e)
            return {}
