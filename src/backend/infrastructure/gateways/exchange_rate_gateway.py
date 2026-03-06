"""Fetch EUR/RUB exchange rate from a public API."""

import logging

import requests

logger = logging.getLogger(__name__)


class ExchangeRateGateway:

    def fetch_eur_rub_rate(self) -> float:
        try:
            resp = requests.get("https://open.er-api.com/v6/latest/EUR", timeout=10)
            resp.raise_for_status()
            rate = resp.json().get("rates", {}).get("RUB", 0.0)
            if rate:
                logger.info("EUR/RUB rate: %.2f", rate)
            else:
                logger.warning("RUB rate missing from exchange rate response")
            return float(rate)
        except Exception as e:
            logger.error("EUR/RUB rate fetch failed: %s", e)
            return 0.0


# Backward-compat module-level function
def fetch_eur_rub_rate() -> float:
    return ExchangeRateGateway().fetch_eur_rub_rate()
