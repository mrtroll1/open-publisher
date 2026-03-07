"""Cloudflare Analytics API gateway — site traffic, performance, security."""

from __future__ import annotations

import logging

import requests

from backend.config import CLOUDFLARE_API_TOKEN, CLOUDFLARE_ZONE_ID

logger = logging.getLogger(__name__)

_GRAPHQL_URL = "https://api.cloudflare.com/client/v4/graphql"


class CloudflareGateway:
    @property
    def available(self) -> bool:
        return bool(CLOUDFLARE_API_TOKEN and CLOUDFLARE_ZONE_ID)

    def _query(self, graphql: str, variables: dict) -> dict | None:
        variables["zoneTag"] = CLOUDFLARE_ZONE_ID
        try:
            resp = requests.post(
                _GRAPHQL_URL,
                headers={
                    "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={"query": graphql, "variables": variables},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("errors"):
                logger.warning("Cloudflare GraphQL errors: %s", data["errors"])
                return None
            return data.get("data")
        except Exception:
            logger.exception("Cloudflare API error")
            return None

    def get_traffic_summary(self, date_from: str, date_to: str) -> dict | None:
        """Overall HTTP traffic: requests, pageviews, unique visitors, bandwidth."""
        query = """
        query ($zoneTag: String!, $since: String!, $until: String!) {
          viewer {
            zones(filter: {zoneTag: $zoneTag}) {
              httpRequests1dGroups(
                filter: {date_geq: $since, date_leq: $until}
                limit: 1000
              ) {
                sum {
                  requests
                  pageViews
                  bytes
                  threats
                  cachedRequests
                  cachedBytes
                }
                uniq { uniques }
              }
            }
          }
        }"""
        data = self._query(query, {"since": date_from, "until": date_to})
        if not data:
            return None
        zones = data.get("viewer", {}).get("zones", [])
        if not zones:
            return None
        groups = zones[0].get("httpRequests1dGroups", [])
        if not groups:
            return None
        total_requests = sum(g["sum"]["requests"] for g in groups)
        total_pageviews = sum(g["sum"]["pageViews"] for g in groups)
        total_bytes = sum(g["sum"]["bytes"] for g in groups)
        total_cached = sum(g["sum"]["cachedRequests"] for g in groups)
        total_threats = sum(g["sum"]["threats"] for g in groups)
        total_uniques = sum(g["uniq"]["uniques"] for g in groups)
        return {
            "requests": total_requests,
            "pageviews": total_pageviews,
            "unique_visitors": total_uniques,
            "bandwidth_mb": round(total_bytes / (1024 * 1024), 1),
            "cached_requests": total_cached,
            "cache_ratio_pct": round(total_cached / total_requests * 100, 1) if total_requests else 0,
            "threats_blocked": total_threats,
        }

    def get_daily_traffic(self, date_from: str, date_to: str) -> list[dict]:
        """Daily breakdown of requests, pageviews, unique visitors."""
        query = """
        query ($zoneTag: String!, $since: String!, $until: String!) {
          viewer {
            zones(filter: {zoneTag: $zoneTag}) {
              httpRequests1dGroups(
                filter: {date_geq: $since, date_leq: $until}
                limit: 1000
                orderBy: [date_ASC]
              ) {
                dimensions { date }
                sum { requests pageViews bytes }
                uniq { uniques }
              }
            }
          }
        }"""
        data = self._query(query, {"since": date_from, "until": date_to})
        if not data:
            return []
        zones = data.get("viewer", {}).get("zones", [])
        if not zones:
            return []
        rows = []
        for g in zones[0].get("httpRequests1dGroups", []):
            rows.append({
                "date": g["dimensions"]["date"],
                "requests": g["sum"]["requests"],
                "pageviews": g["sum"]["pageViews"],
                "unique_visitors": g["uniq"]["uniques"],
                "bandwidth_mb": round(g["sum"]["bytes"] / (1024 * 1024), 1),
            })
        return rows

    def get_top_paths(self, date_from: str, date_to: str, limit: int = 20) -> list[dict]:
        """Top requested URL paths."""
        # Cloudflare GraphQL doesn't have per-path breakdown in the free analytics.
        # Using the REST API for this.
        try:
            resp = requests.get(
                f"https://api.cloudflare.com/client/v4/zones/{CLOUDFLARE_ZONE_ID}/analytics/dashboard",
                headers={"Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}"},
                params={"since": f"{date_from}T00:00:00Z", "until": f"{date_to}T23:59:59Z"},
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json().get("result", {}).get("requests", {}).get("top_paths", [])
        except Exception:
            logger.exception("Cloudflare top paths error")
            return []

    def get_status_codes(self, date_from: str, date_to: str) -> list[dict]:
        """HTTP status code breakdown."""
        query = """
        query ($zoneTag: String!, $since: String!, $until: String!) {
          viewer {
            zones(filter: {zoneTag: $zoneTag}) {
              httpRequests1dGroups(
                filter: {date_geq: $since, date_leq: $until}
                limit: 1000
              ) {
                sum {
                  responseStatusMap {
                    edgeResponseStatus
                    requests
                  }
                }
              }
            }
          }
        }"""
        data = self._query(query, {"since": date_from, "until": date_to})
        if not data:
            return []
        zones = data.get("viewer", {}).get("zones", [])
        if not zones:
            return []
        status_map: dict[int, int] = {}
        for g in zones[0].get("httpRequests1dGroups", []):
            for entry in g.get("sum", {}).get("responseStatusMap", []):
                code = entry["edgeResponseStatus"]
                status_map[code] = status_map.get(code, 0) + entry["requests"]
        return [{"status": k, "requests": v} for k, v in sorted(status_map.items())]
