"""Healthcheck: HTTP domain checks + optional kubectl pod status + Cloudflare."""

import subprocess
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import requests

from backend.brain.base_controller import BaseUseCase
from backend.config import HEALTHCHECK_DOMAINS, KUBECTL_ENABLED
from backend.infrastructure.gateways.cloudflare_gateway import CloudflareGateway


@dataclass
class HealthResult:
    name: str
    status: str  # "ok" or "error"
    details: str


_ICON_OK = "\u2705"
_ICON_ERR = "\u274c"


def format_healthcheck_results(results: list[HealthResult]) -> str:
    lines = [
        f'{_ICON_OK if r.status == "ok" else _ICON_ERR} {r.name} — {r.details}'
        for r in results
    ]
    return "\n".join(lines) if lines else "No checks configured."


def _parse_pod_line(line: str) -> HealthResult | None:
    parts = line.split()
    if len(parts) < 3:
        return None
    pod_name, ready, pod_status = parts[0], parts[1], parts[2]
    is_ok = pod_status == "Running" and ready.split("/")[0] == ready.split("/")[1]
    return HealthResult(pod_name, "ok" if is_ok else "error", f"{pod_status} ({ready})")


def _kubectl_checks() -> list[HealthResult]:
    try:
        proc = subprocess.run(
            ["kubectl", "get", "pods", "--no-headers"],
            capture_output=True, timeout=10, text=True, check=False,
        )
        if proc.returncode != 0:
            return [HealthResult("kubectl", "error", proc.stderr.strip())]
        results = [_parse_pod_line(line) for line in proc.stdout.strip().splitlines()]
        return [r for r in results if r]
    except Exception as e:
        return [HealthResult("kubectl", "error", str(e))]


def _error_rate_check(gw: CloudflareGateway, yesterday: str, today: str) -> HealthResult:
    status_codes = gw.get_status_codes(yesterday, today)
    total = sum(s["requests"] for s in status_codes)
    errors_5xx = sum(s["requests"] for s in status_codes if 500 <= s["status"] < 600)
    error_pct = round(errors_5xx / total * 100, 2) if total else 0
    return HealthResult(
        "Cloudflare 5xx",
        "error" if error_pct > 5 else "ok",
        f"{error_pct}% ({errors_5xx}/{total} запросов за 24ч)",
    )


def _threat_check(summary: dict) -> HealthResult:
    threats = summary.get("threats_blocked", 0)
    return HealthResult("Cloudflare угрозы", "ok", f"{threats} заблокировано за 24ч")


def _cache_check(summary: dict) -> HealthResult:
    cache_pct = summary.get("cache_ratio_pct", 0)
    return HealthResult(
        "Cloudflare кеш",
        "error" if cache_pct < 30 else "ok",
        f"{cache_pct}% запросов из кеша",
    )


def _cloudflare_checks() -> list[HealthResult]:
    gw = CloudflareGateway()
    if not gw.available:
        return []
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    today = date.today().isoformat()
    summary = gw.get_traffic_summary(yesterday, today)
    if not summary:
        return [HealthResult("Cloudflare", "error", "API не отвечает")]
    return [
        _error_rate_check(gw, yesterday, today),
        _threat_check(summary),
        _cache_check(summary),
    ]


def _check_domain(domain: str) -> HealthResult:
    try:
        resp = requests.get(f"https://{domain}", timeout=5)
        status = "ok" if resp.status_code < 400 else "error"
        return HealthResult(domain, status, f"HTTP {resp.status_code}")
    except Exception as e:
        return HealthResult(domain, "error", str(e))


class CheckHealthUseCase(BaseUseCase):
    def execute(self, _prepared: Any, _env: dict, _user: dict) -> list[HealthResult]:
        results = [_check_domain(d) for d in HEALTHCHECK_DOMAINS]
        if KUBECTL_ENABLED:
            results.extend(_kubectl_checks())
        results.extend(_cloudflare_checks())
        return results
