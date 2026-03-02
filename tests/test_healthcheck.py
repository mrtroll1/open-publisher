"""Tests for backend/domain/healthcheck.py"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from backend.domain.healthcheck import (
    HealthResult,
    _kubectl_checks,
    format_healthcheck_results,
    run_healthchecks,
)


# ===================================================================
#  run_healthchecks()
# ===================================================================

class TestRunHealthchecks:

    @patch("backend.domain.healthcheck.KUBECTL_ENABLED", False)
    @patch("backend.domain.healthcheck.HEALTHCHECK_DOMAINS", ["example.com"])
    @patch("backend.domain.healthcheck.requests.get")
    def test_http_domain_up(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200)
        results = run_healthchecks()
        assert len(results) == 1
        assert results[0].status == "ok"
        assert results[0].name == "example.com"
        assert "200" in results[0].details

    @patch("backend.domain.healthcheck.KUBECTL_ENABLED", False)
    @patch("backend.domain.healthcheck.HEALTHCHECK_DOMAINS", ["example.com"])
    @patch("backend.domain.healthcheck.requests.get")
    def test_http_domain_down(self, mock_get):
        mock_get.return_value = MagicMock(status_code=500)
        results = run_healthchecks()
        assert len(results) == 1
        assert results[0].status == "error"
        assert "500" in results[0].details

    @patch("backend.domain.healthcheck.KUBECTL_ENABLED", False)
    @patch("backend.domain.healthcheck.HEALTHCHECK_DOMAINS", ["example.com"])
    @patch("backend.domain.healthcheck.requests.get")
    def test_http_domain_exception(self, mock_get):
        mock_get.side_effect = ConnectionError("refused")
        results = run_healthchecks()
        assert len(results) == 1
        assert results[0].status == "error"
        assert "refused" in results[0].details

    @patch("backend.domain.healthcheck.KUBECTL_ENABLED", False)
    @patch("backend.domain.healthcheck.HEALTHCHECK_DOMAINS", ["a.com", "b.com"])
    @patch("backend.domain.healthcheck.requests.get")
    def test_multiple_domains(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200)
        results = run_healthchecks()
        assert len(results) == 2
        assert results[0].name == "a.com"
        assert results[1].name == "b.com"

    @patch("backend.domain.healthcheck.KUBECTL_ENABLED", True)
    @patch("backend.domain.healthcheck.HEALTHCHECK_DOMAINS", [])
    @patch("backend.domain.healthcheck.subprocess.run")
    def test_kubectl_pods_running(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="web-1 1/1 Running 0 1d\n",
            stderr="",
        )
        results = run_healthchecks()
        assert len(results) == 1
        assert results[0].status == "ok"
        assert results[0].name == "web-1"

    @patch("backend.domain.healthcheck.KUBECTL_ENABLED", True)
    @patch("backend.domain.healthcheck.HEALTHCHECK_DOMAINS", [])
    @patch("backend.domain.healthcheck.subprocess.run")
    def test_kubectl_pods_error(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="connection refused",
        )
        results = run_healthchecks()
        assert len(results) == 1
        assert results[0].status == "error"
        assert results[0].name == "kubectl"

    @patch("backend.domain.healthcheck.KUBECTL_ENABLED", False)
    @patch("backend.domain.healthcheck.HEALTHCHECK_DOMAINS", [])
    def test_kubectl_disabled(self):
        results = run_healthchecks()
        assert results == []


# ===================================================================
#  _kubectl_checks()
# ===================================================================

class TestKubectlChecks:

    @patch("backend.domain.healthcheck.subprocess.run")
    def test_running_ready_pod(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="pod1 1/1 Running 0 1d\n",
            stderr="",
        )
        results = _kubectl_checks()
        assert len(results) == 1
        assert results[0].name == "pod1"
        assert results[0].status == "ok"
        assert "Running" in results[0].details

    @patch("backend.domain.healthcheck.subprocess.run")
    def test_not_ready_pod(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="pod1 0/1 CrashLoopBackOff 5 1d\n",
            stderr="",
        )
        results = _kubectl_checks()
        assert len(results) == 1
        assert results[0].status == "error"
        assert "CrashLoopBackOff" in results[0].details

    @patch("backend.domain.healthcheck.subprocess.run")
    def test_mixed_pods(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="web 1/1 Running 0 1d\nworker 0/1 Error 3 1d\n",
            stderr="",
        )
        results = _kubectl_checks()
        assert len(results) == 2
        assert results[0].status == "ok"
        assert results[1].status == "error"

    @patch("backend.domain.healthcheck.subprocess.run")
    def test_subprocess_failure(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="error: connection refused",
        )
        results = _kubectl_checks()
        assert len(results) == 1
        assert results[0].status == "error"
        assert results[0].name == "kubectl"

    @patch("backend.domain.healthcheck.subprocess.run")
    def test_subprocess_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="kubectl", timeout=10)
        results = _kubectl_checks()
        assert len(results) == 1
        assert results[0].status == "error"
        assert results[0].name == "kubectl"


# ===================================================================
#  format_healthcheck_results()
# ===================================================================

class TestFormatHealthcheckResults:

    def test_all_ok(self):
        results = [
            HealthResult("a.com", "ok", "HTTP 200"),
            HealthResult("b.com", "ok", "HTTP 301"),
        ]
        output = format_healthcheck_results(results)
        assert output.count("\u2705") == 2
        assert "\u274c" not in output

    def test_mixed(self):
        results = [
            HealthResult("a.com", "ok", "HTTP 200"),
            HealthResult("b.com", "error", "HTTP 500"),
        ]
        output = format_healthcheck_results(results)
        assert "\u2705" in output
        assert "\u274c" in output
        assert "a.com" in output
        assert "b.com" in output

    def test_empty(self):
        output = format_healthcheck_results([])
        assert output == "No checks configured."
