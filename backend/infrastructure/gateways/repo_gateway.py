"""Gateway for git repo access — clone, grep search, file reading."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from common.config import REPOS_DIR, REPO_URLS

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
        self._repo_urls: dict[str, str] = dict(REPO_URLS)

    def _repo_path(self, name: str) -> Path:
        return self._repos_dir / name

    def ensure_repos(self) -> None:
        if not self._repo_urls:
            return
        try:
            self._repos_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning("Cannot create repos dir %s: %s", self._repos_dir, e)
            return
        for name, url in self._repo_urls.items():
            path = self._repo_path(name)
            try:
                if path.exists():
                    shutil.rmtree(path)
                subprocess.run(
                    ["git", "clone", "--depth", "1", url, str(path)],
                    capture_output=True, timeout=60,
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

    def fetch_snippets(self, search_terms: list[str], max_files: int = 5, context_lines: int = 25) -> str:
        seen_files: dict[str, tuple[str, int]] = {}
        for term in search_terms:
            for rel_path, lineno, _ in self.search_code(term):
                if rel_path not in seen_files:
                    seen_files[rel_path] = (rel_path.split("/", 1)[0], lineno)

        snippets = []
        for rel_path, (repo, lineno) in list(seen_files.items())[:max_files]:
            filepath = rel_path.split("/", 1)[1] if "/" in rel_path else rel_path
            content = self.read_file(repo, filepath)
            if not content:
                continue
            lines = content.splitlines()
            start = max(0, lineno - context_lines)
            end = min(len(lines), lineno + context_lines)
            snippet = "\n".join(lines[start:end])
            snippets.append(f"### {rel_path} (lines {start + 1}-{end})\n```\n{snippet}\n```")

        if not snippets:
            return ""
        return "## Контекст из кода\n\n" + "\n\n".join(snippets)

    def read_file(self, repo: str, filepath: str, max_lines: int = 200) -> str:
        full = (self._repo_path(repo) / filepath).resolve()
        if not full.is_relative_to(self._repos_dir) or not full.exists():
            return ""
        try:
            lines = full.read_text(encoding="utf-8", errors="replace").splitlines()
            return "\n".join(lines[:max_lines])
        except Exception:
            return ""
