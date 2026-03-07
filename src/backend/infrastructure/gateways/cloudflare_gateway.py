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
            raise RuntimeError(f"Cloudflare GraphQL errors: {data['errors']}")
        return data.get("data")

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
        return [
            {
                "date": g["dimensions"]["date"],
                "requests": g["sum"]["requests"],
                "pageviews": g["sum"]["pageViews"],
                "unique_visitors": g["uniq"]["uniques"],
                "bandwidth_mb": round(g["sum"]["bytes"] / (1024 * 1024), 1),
            }
            for g in zones[0].get("httpRequests1dGroups", [])
        ]

    def get_top_paths(self, date_from: str, date_to: str, limit: int = 20) -> list[dict]:
        """Top requested URL paths using adaptive groups."""
        query = """
        query ($zoneTag: String!, $since: String!, $until: String!, $limit: Int!) {
          viewer {
            zones(filter: {zoneTag: $zoneTag}) {
              httpRequestsAdaptiveGroups(
                filter: {date_geq: $since, date_leq: $until}
                limit: $limit
                orderBy: [count_DESC]
              ) {
                count
                dimensions {
                  clientRequestPath
                }
              }
            }
          }
        }"""
        data = self._query(query, {"since": date_from, "until": date_to, "limit": limit})
        if not data:
            return []
        zones = data.get("viewer", {}).get("zones", [])
        if not zones:
            return []
        return [
            {"path": g["dimensions"]["clientRequestPath"], "requests": g["count"]}
            for g in zones[0].get("httpRequestsAdaptiveGroups", [])
        ]

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

    def get_top_countries(self, date_from: str, date_to: str, limit: int = 20) -> list[dict]:
        """Top countries by request count."""
        query = """
        query ($zoneTag: String!, $since: String!, $until: String!) {
          viewer {
            zones(filter: {zoneTag: $zoneTag}) {
              httpRequests1dGroups(
                filter: {date_geq: $since, date_leq: $until}
                limit: 1000
              ) {
                sum {
                  countryMap {
                    clientCountryName
                    requests
                    threats
                    bytes
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
        country_map: dict[str, dict] = {}
        for g in zones[0].get("httpRequests1dGroups", []):
            for entry in g.get("sum", {}).get("countryMap", []):
                name = entry["clientCountryName"]
                if name not in country_map:
                    country_map[name] = {"country": name, "requests": 0, "threats": 0, "bandwidth_mb": 0.0}
                country_map[name]["requests"] += entry["requests"]
                country_map[name]["threats"] += entry["threats"]
                country_map[name]["bandwidth_mb"] += entry["bytes"] / (1024 * 1024)
        rows = sorted(country_map.values(), key=lambda r: r["requests"], reverse=True)[:limit]
        for r in rows:
            r["bandwidth_mb"] = round(r["bandwidth_mb"], 1)
        return rows

    def get_threat_summary(self, date_from: str, date_to: str) -> dict | None:
        """Threat/security summary: total threats, top threat countries, threat types."""
        query = """
        query ($zoneTag: String!, $since: String!, $until: String!) {
          viewer {
            zones(filter: {zoneTag: $zoneTag}) {
              httpRequests1dGroups(
                filter: {date_geq: $since, date_leq: $until}
                limit: 1000
              ) {
                sum {
                  threats
                  threatPathingMap {
                    threatPathingName
                    requests
                  }
                  countryMap {
                    clientCountryName
                    threats
                  }
                }
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
        total_threats = sum(g["sum"]["threats"] for g in groups)
        threat_types: dict[str, int] = {}
        threat_countries: dict[str, int] = {}
        for g in groups:
            for entry in g["sum"].get("threatPathingMap", []):
                name = entry["threatPathingName"]
                threat_types[name] = threat_types.get(name, 0) + entry["requests"]
            for entry in g["sum"].get("countryMap", []):
                if entry["threats"] > 0:
                    name = entry["clientCountryName"]
                    threat_countries[name] = threat_countries.get(name, 0) + entry["threats"]
        top_types = sorted(threat_types.items(), key=lambda x: x[1], reverse=True)[:10]
        top_countries = sorted(threat_countries.items(), key=lambda x: x[1], reverse=True)[:10]
        return {
            "total_threats": total_threats,
            "top_threat_types": [{"type": k, "count": v} for k, v in top_types],
            "top_threat_countries": [{"country": k, "count": v} for k, v in top_countries],
        }

    def get_content_types(self, date_from: str, date_to: str) -> list[dict]:
        """Breakdown by content type."""
        query = """
        query ($zoneTag: String!, $since: String!, $until: String!) {
          viewer {
            zones(filter: {zoneTag: $zoneTag}) {
              httpRequests1dGroups(
                filter: {date_geq: $since, date_leq: $until}
                limit: 1000
              ) {
                sum {
                  contentTypeMap {
                    edgeResponseContentTypeName
                    requests
                    bytes
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
        ct_map: dict[str, dict] = {}
        for g in zones[0].get("httpRequests1dGroups", []):
            for entry in g.get("sum", {}).get("contentTypeMap", []):
                name = entry["edgeResponseContentTypeName"]
                if name not in ct_map:
                    ct_map[name] = {"content_type": name, "requests": 0, "bandwidth_mb": 0.0}
                ct_map[name]["requests"] += entry["requests"]
                ct_map[name]["bandwidth_mb"] += entry["bytes"] / (1024 * 1024)
        rows = sorted(ct_map.values(), key=lambda r: r["requests"], reverse=True)
        for r in rows:
            r["bandwidth_mb"] = round(r["bandwidth_mb"], 1)
        return rows
