"""Healthcheck: HTTP domain checks + optional kubectl pod status."""

import subprocess
from dataclasses import dataclass
from typing import Any

import requests

from backend.brain.base_controller import BaseUseCase
from common.config import HEALTHCHECK_DOMAINS, KUBECTL_ENABLED


@dataclass
class HealthResult:
    name: str
    status: str  # "ok" or "error"
    details: str


def run_healthchecks() -> list[HealthResult]:
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

    return results


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


def format_healthcheck_results(results: list[HealthResult]) -> str:
    lines = []
    for r in results:
        icon = "\u2705" if r.status == "ok" else "\u274c"
        lines.append(f"{icon} {r.name} — {r.details}")
    return "\n".join(lines) if lines else "No checks configured."


class CheckHealthUseCase(BaseUseCase):
    def execute(self, prepared: Any, env: dict, user: dict) -> Any:
        return run_healthchecks()


