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

    def _fetch_groups(
        self, date_from: str, date_to: str, query: str,
        group_key: str = "httpRequests1dGroups", extra_vars: dict | None = None,
    ) -> list[dict]:
        variables = {"since": date_from, "until": date_to, **(extra_vars or {})}
        data = self._query(query, variables)
        if not data:
            return []
        zones = data.get("viewer", {}).get("zones", [])
        if not zones:
            return []
        return zones[0].get(group_key, [])

    def _aggregate_map(
        self, groups: list[dict], map_key: str,
        name_field: str, value_fields: list[str],
    ) -> dict[str, dict]:
        result: dict[str, dict] = {}
        for g in groups:
            for entry in g.get("sum", {}).get(map_key, []):
                name = entry[name_field]
                if name not in result:
                    result[name] = {f: 0 for f in value_fields}
                for f in value_fields:
                    result[name][f] += entry[f]
        return result

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
        groups = self._fetch_groups(date_from, date_to, query)
        if not groups:
            return None
        return self._build_traffic_summary(groups)

    def _build_traffic_summary(self, groups: list[dict]) -> dict:
        total_requests = sum(g["sum"]["requests"] for g in groups)
        total_cached = sum(g["sum"]["cachedRequests"] for g in groups)
        return {
            "requests": total_requests,
            "pageviews": sum(g["sum"]["pageViews"] for g in groups),
            "unique_visitors": sum(g["uniq"]["uniques"] for g in groups),
            "bandwidth_mb": round(sum(g["sum"]["bytes"] for g in groups) / (1024 * 1024), 1),
            "cached_requests": total_cached,
            "cache_ratio_pct": round(total_cached / total_requests * 100, 1) if total_requests else 0,
            "threats_blocked": sum(g["sum"]["threats"] for g in groups),
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
        groups = self._fetch_groups(date_from, date_to, query)
        return [self._format_daily_row(g) for g in groups]

    def _format_daily_row(self, g: dict) -> dict:
        return {
            "date": g["dimensions"]["date"],
            "requests": g["sum"]["requests"],
            "pageviews": g["sum"]["pageViews"],
            "unique_visitors": g["uniq"]["uniques"],
            "bandwidth_mb": round(g["sum"]["bytes"] / (1024 * 1024), 1),
        }

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
        groups = self._fetch_groups(
            date_from, date_to, query,
            group_key="httpRequestsAdaptiveGroups", extra_vars={"limit": limit},
        )
        return [
            {"path": g["dimensions"]["clientRequestPath"], "requests": g["count"]}
            for g in groups
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
        groups = self._fetch_groups(date_from, date_to, query)
        agg = self._aggregate_map(groups, "responseStatusMap", "edgeResponseStatus", ["requests"])
        return [{"status": k, "requests": v["requests"]} for k, v in sorted(agg.items())]

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
        groups = self._fetch_groups(date_from, date_to, query)
        agg = self._aggregate_map(groups, "countryMap", "clientCountryName", ["requests", "threats", "bytes"])
        return self._format_country_rows(agg, limit)

    def _format_country_rows(self, agg: dict[str, dict], limit: int) -> list[dict]:
        rows = [
            {"country": name, "requests": v["requests"], "threats": v["threats"],
             "bandwidth_mb": round(v["bytes"] / (1024 * 1024), 1)}
            for name, v in agg.items()
        ]
        return sorted(rows, key=lambda r: r["requests"], reverse=True)[:limit]

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
        groups = self._fetch_groups(date_from, date_to, query)
        if not groups:
            return None
        return self._build_threat_summary(groups)

    def _build_threat_summary(self, groups: list[dict]) -> dict:
        threat_types = self._aggregate_map(groups, "threatPathingMap", "threatPathingName", ["requests"])
        threat_countries = self._collect_threat_countries(groups)
        top_types = sorted(threat_types.items(), key=lambda x: x[1]["requests"], reverse=True)[:10]
        top_countries = sorted(threat_countries.items(), key=lambda x: x[1], reverse=True)[:10]
        return {
            "total_threats": sum(g["sum"]["threats"] for g in groups),
            "top_threat_types": [{"type": k, "count": v["requests"]} for k, v in top_types],
            "top_threat_countries": [{"country": k, "count": v} for k, v in top_countries],
        }

    def _collect_threat_countries(self, groups: list[dict]) -> dict[str, int]:
        result: dict[str, int] = {}
        for g in groups:
            for entry in g["sum"].get("countryMap", []):
                if entry["threats"] > 0:
                    name = entry["clientCountryName"]
                    result[name] = result.get(name, 0) + entry["threats"]
        return result

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
        groups = self._fetch_groups(date_from, date_to, query)
        agg = self._aggregate_map(groups, "contentTypeMap", "edgeResponseContentTypeName", ["requests", "bytes"])
        return self._format_content_type_rows(agg)

    def _format_content_type_rows(self, agg: dict[str, dict]) -> list[dict]:
        rows = [
            {"content_type": name, "requests": v["requests"],
             "bandwidth_mb": round(v["bytes"] / (1024 * 1024), 1)}
            for name, v in agg.items()
        ]
        return sorted(rows, key=lambda r: r["requests"], reverse=True)
