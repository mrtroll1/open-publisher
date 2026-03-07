"""Yandex Metrica API gateway — site analytics (pageviews, visitors, traffic sources)."""

from __future__ import annotations

import logging

import requests

from backend.config import YANDEX_METRICA_COUNTER_ID, YANDEX_METRICA_TOKEN

logger = logging.getLogger(__name__)

_BASE = "https://api-metrika.yandex.net/stat/v1"


class YandexMetricaGateway:
    @property
    def available(self) -> bool:
        return bool(YANDEX_METRICA_TOKEN and YANDEX_METRICA_COUNTER_ID)

    def _get(self, endpoint: str, params: dict) -> dict | None:
        params["id"] = YANDEX_METRICA_COUNTER_ID
        try:
            resp = requests.get(
                f"{_BASE}/{endpoint}",
                headers={"Authorization": f"OAuth {YANDEX_METRICA_TOKEN}"},
                params=params,
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception:
            logger.exception("Yandex Metrica API error: %s %s", endpoint, params)
            return None

    def get_popular_pages(self, date_from: str, date_to: str, limit: int = 20) -> list[dict]:
        """Top pages by pageviews. Dates: YYYY-MM-DD."""
        data = self._get("data", {
            "metrics": "ym:pv:pageviews,ym:pv:users",
            "dimensions": "ym:pv:URLPath",
            "sort": "-ym:pv:pageviews",
            "date1": date_from,
            "date2": date_to,
            "limit": limit,
        })
        if not data:
            return []
        rows = []
        for item in data.get("data", []):
            dims = item.get("dimensions", [{}])
            metrics = item.get("metrics", [0, 0])
            rows.append({
                "url_path": dims[0].get("name", ""),
                "pageviews": int(metrics[0]),
                "visitors": int(metrics[1]),
            })
        return rows

    def get_traffic_summary(self, date_from: str, date_to: str) -> dict | None:
        """Overall traffic summary: visits, pageviews, users, bounce rate."""
        data = self._get("data", {
            "metrics": "ym:s:visits,ym:s:pageviews,ym:s:users,ym:s:bounceRate,ym:s:avgVisitDurationSeconds",
            "date1": date_from,
            "date2": date_to,
        })
        if not data:
            return None
        totals = data.get("totals", [])
        if len(totals) < 5:
            return None
        return {
            "visits": int(totals[0]),
            "pageviews": int(totals[1]),
            "users": int(totals[2]),
            "bounce_rate": round(totals[3], 1),
            "avg_duration_sec": int(totals[4]),
        }

    def get_traffic_sources(self, date_from: str, date_to: str, limit: int = 10) -> list[dict]:
        """Traffic by source type."""
        data = self._get("data", {
            "metrics": "ym:s:visits,ym:s:users",
            "dimensions": "ym:s:trafficSource",
            "sort": "-ym:s:visits",
            "date1": date_from,
            "date2": date_to,
            "limit": limit,
        })
        if not data:
            return []
        rows = []
        for item in data.get("data", []):
            dims = item.get("dimensions", [{}])
            metrics = item.get("metrics", [0, 0])
            rows.append({
                "source": dims[0].get("name", ""),
                "visits": int(metrics[0]),
                "users": int(metrics[1]),
            })
        return rows

    def get_daily_traffic(self, date_from: str, date_to: str) -> list[dict]:
        """Daily visits and pageviews."""
        data = self._get("data/bytime", {
            "metrics": "ym:s:visits,ym:s:pageviews",
            "group": "day",
            "date1": date_from,
            "date2": date_to,
        })
        if not data:
            return []
        time_intervals = data.get("time_intervals", [])
        totals = data.get("totals", [[], []])
        rows = []
        for i, interval in enumerate(time_intervals):
            date = interval[0][:10] if interval else ""
            rows.append({
                "date": date,
                "visits": int(totals[0][i]) if i < len(totals[0]) else 0,
                "pageviews": int(totals[1][i]) if i < len(totals[1]) else 0,
            })
        return rows
