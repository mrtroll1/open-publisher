"""Tests for backend/infrastructure/gateways/exchange_rate_gateway.py"""

from unittest.mock import MagicMock, patch

import pytest
import requests


# ===================================================================
#  fetch_eur_rub_rate()
# ===================================================================

class TestFetchEurRubRate:

    @patch("backend.infrastructure.gateways.exchange_rate_gateway.requests.get")
    def test_returns_rate(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"rates": {"RUB": 95.42, "USD": 1.08}},
        )
        mock_get.return_value.raise_for_status = MagicMock()
        from backend.infrastructure.gateways.exchange_rate_gateway import fetch_eur_rub_rate
        rate = fetch_eur_rub_rate()
        assert rate == 95.42

    @patch("backend.infrastructure.gateways.exchange_rate_gateway.requests.get")
    def test_missing_rub_returns_zero(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"rates": {"USD": 1.08}},
        )
        mock_get.return_value.raise_for_status = MagicMock()
        from backend.infrastructure.gateways.exchange_rate_gateway import fetch_eur_rub_rate
        rate = fetch_eur_rub_rate()
        assert rate == 0.0

    @patch("backend.infrastructure.gateways.exchange_rate_gateway.requests.get")
    def test_missing_rates_key_returns_zero(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"result": "success"},
        )
        mock_get.return_value.raise_for_status = MagicMock()
        from backend.infrastructure.gateways.exchange_rate_gateway import fetch_eur_rub_rate
        rate = fetch_eur_rub_rate()
        assert rate == 0.0

    @patch("backend.infrastructure.gateways.exchange_rate_gateway.requests.get")
    def test_http_error_returns_zero(self, mock_get):
        mock_get.return_value = MagicMock(status_code=500)
        mock_get.return_value.raise_for_status.side_effect = requests.HTTPError("500")
        from backend.infrastructure.gateways.exchange_rate_gateway import fetch_eur_rub_rate
        rate = fetch_eur_rub_rate()
        assert rate == 0.0

    @patch("backend.infrastructure.gateways.exchange_rate_gateway.requests.get")
    def test_connection_error_returns_zero(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("refused")
        from backend.infrastructure.gateways.exchange_rate_gateway import fetch_eur_rub_rate
        rate = fetch_eur_rub_rate()
        assert rate == 0.0

    @patch("backend.infrastructure.gateways.exchange_rate_gateway.requests.get")
    def test_timeout_returns_zero(self, mock_get):
        mock_get.side_effect = requests.Timeout("timed out")
        from backend.infrastructure.gateways.exchange_rate_gateway import fetch_eur_rub_rate
        rate = fetch_eur_rub_rate()
        assert rate == 0.0
