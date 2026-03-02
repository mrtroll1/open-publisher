"""Tests for backend/infrastructure/gateways/repo_gateway.py"""

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _make_gw(repos_dir: str, republic_url: str = "https://git.example.com/republic.git",
             redefine_url: str = ""):
    """Create a RepoGateway with patched config values."""
    with patch("backend.infrastructure.gateways.repo_gateway.REPOS_DIR", repos_dir), \
         patch("backend.infrastructure.gateways.repo_gateway.REPUBLIC_REPO_URL", republic_url), \
         patch("backend.infrastructure.gateways.repo_gateway.REDEFINE_REPO_URL", redefine_url):
        from backend.infrastructure.gateways.repo_gateway import RepoGateway
        return RepoGateway()


# ===================================================================
#  search_code()
# ===================================================================

class TestSearchCode:

    def test_parses_grep_output(self, tmp_path):
        gw = _make_gw(str(tmp_path))
        repo_path = tmp_path / "republic"
        repo_path.mkdir()
        with patch("backend.infrastructure.gateways.repo_gateway.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout=f"{repo_path}/app/main.py:42:def hello():\n"
                       f"{repo_path}/app/utils.py:10:import os\n",
            )
            results = gw.search_code("hello")
            assert len(results) == 2
            assert results[0] == ("republic/app/main.py", 42, "def hello():")
            assert results[1] == ("republic/app/utils.py", 10, "import os")

    def test_limits_to_20_results(self, tmp_path):
        gw = _make_gw(str(tmp_path))
        repo_path = tmp_path / "republic"
        repo_path.mkdir()
        with patch("backend.infrastructure.gateways.repo_gateway.subprocess.run") as mock_run:
            lines = [f"{repo_path}/f.py:{i}:line{i}" for i in range(1, 31)]
            mock_run.return_value = MagicMock(stdout="\n".join(lines))
            results = gw.search_code("x")
            assert len(results) == 20

    def test_skips_nonexistent_repo(self, tmp_path):
        gw = _make_gw(str(tmp_path))
        # Don't create the repo directory
        with patch("backend.infrastructure.gateways.repo_gateway.subprocess.run") as mock_run:
            results = gw.search_code("hello")
            assert results == []
            mock_run.assert_not_called()

    def test_single_repo_filter(self, tmp_path):
        gw = _make_gw(str(tmp_path), redefine_url="https://git.example.com/redefine.git")
        (tmp_path / "republic").mkdir()
        (tmp_path / "redefine").mkdir()
        with patch("backend.infrastructure.gateways.repo_gateway.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout=f"{tmp_path}/republic/a.py:1:x\n"
            )
            gw.search_code("x", repo="republic")
            assert mock_run.call_count == 1
            call_cmd = mock_run.call_args[0][0]
            assert str(tmp_path / "republic") in call_cmd

    def test_no_repos_configured(self, tmp_path):
        gw = _make_gw(str(tmp_path), republic_url="", redefine_url="")
        assert gw.search_code("anything") == []

    def test_skips_malformed_lines(self, tmp_path):
        gw = _make_gw(str(tmp_path))
        repo_path = tmp_path / "republic"
        repo_path.mkdir()
        with patch("backend.infrastructure.gateways.repo_gateway.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout=f"Binary file matches\n"
                       f"{repo_path}/a.py:notanum:content\n"
                       f"{repo_path}/b.py:5:valid\n",
            )
            results = gw.search_code("x")
            assert len(results) == 1
            assert results[0] == ("republic/b.py", 5, "valid")

    def test_grep_exception_returns_empty(self, tmp_path):
        gw = _make_gw(str(tmp_path))
        (tmp_path / "republic").mkdir()
        with patch("backend.infrastructure.gateways.repo_gateway.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="grep", timeout=30)
            results = gw.search_code("x")
            assert results == []

    def test_multi_repo_search(self, tmp_path):
        gw = _make_gw(str(tmp_path), redefine_url="https://git.example.com/redefine.git")
        (tmp_path / "republic").mkdir()
        (tmp_path / "redefine").mkdir()
        with patch("backend.infrastructure.gateways.repo_gateway.subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout=f"{tmp_path}/republic/a.py:1:hit\n"),
                MagicMock(stdout=f"{tmp_path}/redefine/b.py:2:hit\n"),
            ]
            results = gw.search_code("hit")
            assert len(results) == 2
            assert mock_run.call_count == 2


# ===================================================================
#  read_file()
# ===================================================================

class TestReadFile:

    def test_reads_file_content(self, tmp_path):
        gw = _make_gw(str(tmp_path))
        repo_path = tmp_path / "republic"
        repo_path.mkdir()
        (repo_path / "hello.py").write_text("line1\nline2\nline3\n")
        content = gw.read_file("republic", "hello.py")
        # splitlines() + join drops trailing newline
        assert content == "line1\nline2\nline3"

    def test_max_lines(self, tmp_path):
        gw = _make_gw(str(tmp_path))
        repo_path = tmp_path / "republic"
        repo_path.mkdir()
        (repo_path / "big.py").write_text("\n".join(f"line{i}" for i in range(300)))
        content = gw.read_file("republic", "big.py", max_lines=5)
        assert len(content.splitlines()) == 5

    def test_path_traversal_blocked(self, tmp_path):
        gw = _make_gw(str(tmp_path))
        (tmp_path / "republic").mkdir()
        result = gw.read_file("republic", "../../etc/passwd")
        assert result == ""

    def test_nonexistent_file(self, tmp_path):
        gw = _make_gw(str(tmp_path))
        (tmp_path / "republic").mkdir()
        result = gw.read_file("republic", "does_not_exist.py")
        assert result == ""

    def test_nonexistent_repo(self, tmp_path):
        gw = _make_gw(str(tmp_path))
        result = gw.read_file("unknown_repo", "file.py")
        assert result == ""

    def test_subdirectory_read(self, tmp_path):
        gw = _make_gw(str(tmp_path))
        repo_path = tmp_path / "republic"
        (repo_path / "app" / "models").mkdir(parents=True)
        (repo_path / "app" / "models" / "user.py").write_text("class User: pass")
        content = gw.read_file("republic", "app/models/user.py")
        assert content == "class User: pass"


# ===================================================================
#  fetch_snippets()
# ===================================================================

class TestFetchSnippets:

    def test_assembles_snippets(self, tmp_path):
        gw = _make_gw(str(tmp_path))
        repo_path = tmp_path / "republic"
        repo_path.mkdir()
        (repo_path / "app.py").write_text("\n".join(f"line{i}" for i in range(50)))
        with patch("backend.infrastructure.gateways.repo_gateway.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout=f"{repo_path}/app.py:10:match\n"
            )
            result = gw.fetch_snippets(["match"])
            assert "## Контекст из кода" in result
            assert "republic/app.py" in result

    def test_deduplicates_files(self, tmp_path):
        gw = _make_gw(str(tmp_path))
        repo_path = tmp_path / "republic"
        repo_path.mkdir()
        (repo_path / "app.py").write_text("\n".join(f"line{i}" for i in range(50)))
        with patch("backend.infrastructure.gateways.repo_gateway.subprocess.run") as mock_run:
            # Both search terms find the same file
            mock_run.return_value = MagicMock(
                stdout=f"{repo_path}/app.py:5:first\n"
                       f"{repo_path}/app.py:10:second\n"
            )
            result = gw.fetch_snippets(["first", "second"])
            # File appears only once in output (one ### header)
            assert result.count("republic/app.py") == 1

    def test_max_files_limit(self, tmp_path):
        gw = _make_gw(str(tmp_path))
        repo_path = tmp_path / "republic"
        repo_path.mkdir()
        for i in range(10):
            (repo_path / f"f{i}.py").write_text(f"content{i}")
        with patch("backend.infrastructure.gateways.repo_gateway.subprocess.run") as mock_run:
            lines = "\n".join(f"{repo_path}/f{i}.py:1:content{i}" for i in range(10))
            mock_run.return_value = MagicMock(stdout=lines)
            result = gw.fetch_snippets(["content"], max_files=2)
            assert result.count("###") == 2

    def test_empty_results(self, tmp_path):
        gw = _make_gw(str(tmp_path))
        (tmp_path / "republic").mkdir()
        with patch("backend.infrastructure.gateways.repo_gateway.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="")
            result = gw.fetch_snippets(["nothing"])
            assert result == ""

    def test_line_range_calculation(self, tmp_path):
        gw = _make_gw(str(tmp_path))
        repo_path = tmp_path / "republic"
        repo_path.mkdir()
        # 100 lines, match at line 10, context_lines=5
        (repo_path / "app.py").write_text("\n".join(f"L{i}" for i in range(100)))
        with patch("backend.infrastructure.gateways.repo_gateway.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout=f"{repo_path}/app.py:10:L10\n"
            )
            result = gw.fetch_snippets(["L10"], context_lines=5)
            # Should show lines 6-15 (start=max(0,10-5)=5, end=min(100,10+5)=15)
            assert "(lines 6-15)" in result


# ===================================================================
#  ensure_repos()
# ===================================================================

class TestEnsureRepos:

    def test_clones_when_not_exists(self, tmp_path):
        gw = _make_gw(str(tmp_path))
        # Remove the republic dir if it exists
        republic_path = tmp_path / "republic"
        if republic_path.exists():
            republic_path.rmdir()
        with patch("backend.infrastructure.gateways.repo_gateway.subprocess.run") as mock_run:
            gw.ensure_repos()
            call_cmd = mock_run.call_args[0][0]
            assert call_cmd[0] == "git"
            assert call_cmd[1] == "clone"

    def test_pulls_when_exists(self, tmp_path):
        gw = _make_gw(str(tmp_path))
        (tmp_path / "republic").mkdir()
        with patch("backend.infrastructure.gateways.repo_gateway.subprocess.run") as mock_run:
            gw.ensure_repos()
            call_cmd = mock_run.call_args[0][0]
            assert call_cmd[0] == "git"
            assert "pull" in call_cmd

    def test_no_urls_is_noop(self, tmp_path):
        gw = _make_gw(str(tmp_path), republic_url="", redefine_url="")
        with patch("backend.infrastructure.gateways.repo_gateway.subprocess.run") as mock_run:
            gw.ensure_repos()
            mock_run.assert_not_called()

    def test_exception_does_not_propagate(self, tmp_path):
        gw = _make_gw(str(tmp_path))
        with patch("backend.infrastructure.gateways.repo_gateway.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=30)
            # Should not raise
            gw.ensure_repos()
