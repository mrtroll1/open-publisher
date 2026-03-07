"""Healthcheck: HTTP domain checks + optional kubectl pod status + Cloudflare."""

import subprocess
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import requests

from backend.brain.base_controller import BaseUseCase
from backend.config import HEALTHCHECK_DOMAINS, KUBECTL_ENABLED


@dataclass
class HealthResult:
    name: str
    status: str  # "ok" or "error"
    details: str


def format_healthcheck_results(results: list[HealthResult]) -> str:
    lines = []
    for r in results:
        icon = "\u2705" if r.status == "ok" else "\u274c"
        lines.append(f"{icon} {r.name} — {r.details}")
    return "\n".join(lines) if lines else "No checks configured."


def _kubectl_checks() -> list[HealthResult]:
    try:
        proc = subprocess.run(
            ["kubectl", "get", "pods", "--no-headers"],
            capture_output=True, timeout=10, text=True,
        )
        if proc.returncode != 0:
            return [HealthResult("kubectl", "error", proc.stderr.strip())]

        results = []
        for line in proc.stdout.strip().splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            pod_name, ready, pod_status = parts[0], parts[1], parts[2]
            is_ok = pod_status == "Running" and ready.split("/")[0] == ready.split("/")[1]
            results.append(HealthResult(
                pod_name,
                "ok" if is_ok else "error",
                f"{pod_status} ({ready})",
            ))
        return results
    except Exception as e:
        return [HealthResult("kubectl", "error", str(e))]


def _cloudflare_checks() -> list[HealthResult]:
    from backend.infrastructure.gateways.cloudflare_gateway import CloudflareGateway
    gw = CloudflareGateway()
    if not gw.available:
        return []

    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    summary = gw.get_traffic_summary(yesterday, today)
    if not summary:
        return [HealthResult("Cloudflare", "error", "API не отвечает")]

    results = []

    # Error rate from status codes
    status_codes = gw.get_status_codes(yesterday, today)
    total = sum(s["requests"] for s in status_codes)
    errors_5xx = sum(s["requests"] for s in status_codes if 500 <= s["status"] < 600)
    error_pct = round(errors_5xx / total * 100, 2) if total else 0
    status = "error" if error_pct > 5 else "ok"
    results.append(HealthResult(
        "Cloudflare 5xx",
        status,
        f"{error_pct}% ({errors_5xx}/{total} запросов за 24ч)",
    ))

    # Threats
    threats = summary.get("threats_blocked", 0)
    results.append(HealthResult(
        "Cloudflare угрозы",
        "ok",
        f"{threats} заблокировано за 24ч",
    ))

    # Cache ratio
    cache_pct = summary.get("cache_ratio_pct", 0)
    status = "error" if cache_pct < 30 else "ok"
    results.append(HealthResult(
        "Cloudflare кеш",
        status,
        f"{cache_pct}% запросов из кеша",
    ))

    return results


class CheckHealthUseCase(BaseUseCase):
    def execute(self, prepared: Any, env: dict, user: dict) -> list[HealthResult]:
        results = []
        for domain in HEALTHCHECK_DOMAINS:
            try:
                resp = requests.get(f"https://{domain}", timeout=5)
                if resp.status_code < 400:
                    results.append(HealthResult(domain, "ok", f"HTTP {resp.status_code}"))
                else:
                    results.append(HealthResult(domain, "error", f"HTTP {resp.status_code}"))
            except Exception as e:
                results.append(HealthResult(domain, "error", str(e)))

        if KUBECTL_ENABLED:
            results.extend(_kubectl_checks())

        results.extend(_cloudflare_checks())

        return results
