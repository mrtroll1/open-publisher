"""Gateway for git repo access — clone/pull, grep search, file reading."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from common.config import REPOS_DIR, REPUBLIC_REPO_URL, REDEFINE_REPO_URL

logger = logging.getLogger(__name__)

_GREP_EXTENSIONS = (
    "--include=*.py", "--include=*.js", "--include=*.ts",
    "--include=*.html", "--include=*.css",
    "--include=*.yml", "--include=*.yaml",
    "--include=*.json", "--include=*.md",
)


class RepoGateway:

    def __init__(self):
        self._repos_dir = Path(REPOS_DIR).resolve()
        self._repo_urls: dict[str, str] = {}
        if REPUBLIC_REPO_URL:
            self._repo_urls["republic"] = REPUBLIC_REPO_URL
        if REDEFINE_REPO_URL:
            self._repo_urls["redefine"] = REDEFINE_REPO_URL

    def _repo_path(self, name: str) -> Path:
        return self._repos_dir / name

    def ensure_repos(self) -> None:
        if not self._repo_urls:
            return
        self._repos_dir.mkdir(parents=True, exist_ok=True)
        for name, url in self._repo_urls.items():
            path = self._repo_path(name)
            try:
                if path.exists():
                    subprocess.run(
                        ["git", "-C", str(path), "pull", "--ff-only"],
                        capture_output=True, timeout=30,
                    )
                else:
                    subprocess.run(
                        ["git", "clone", "--depth", "1", url, str(path)],
                        capture_output=True, timeout=30,
                    )
            except Exception as e:
                logger.warning("Git op failed for %s: %s", name, e)

    def search_code(
        self, query: str, repo: str | None = None,
    ) -> list[tuple[str, int, str]]:
        if not self._repo_urls:
            return []
        targets = [repo] if repo and repo in self._repo_urls else list(self._repo_urls)
        results: list[tuple[str, int, str]] = []
        for name in targets:
            path = self._repo_path(name)
            if not path.exists():
                continue
            try:
                proc = subprocess.run(
                    ["grep", "-rn", *_GREP_EXTENSIONS, "--", query, str(path)],
                    capture_output=True, text=True, timeout=30,
                )
                for line in proc.stdout.splitlines()[:20]:
                    parts = line.split(":", 2)
                    if len(parts) >= 3:
                        filepath = parts[0]
                        try:
                            lineno = int(parts[1])
                        except ValueError:
                            continue
                        content = parts[2]
                        # Make filepath relative to repos dir
                        rel = filepath.replace(str(self._repos_dir) + "/", "", 1)
                        results.append((rel, lineno, content))
            except Exception as e:
                logger.warning("Grep failed for %s: %s", name, e)
        return results[:20]

    def read_file(self, repo: str, filepath: str, max_lines: int = 200) -> str:
        full = (self._repo_path(repo) / filepath).resolve()
        if not full.is_relative_to(self._repos_dir) or not full.exists():
            return ""
        try:
            lines = full.read_text(encoding="utf-8", errors="replace").splitlines()
            return "\n".join(lines[:max_lines])
        except Exception:
            return ""
