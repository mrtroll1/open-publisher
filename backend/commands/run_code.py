"""Run Claude Code CLI as a subprocess."""

from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from backend.brain.base_controller import BaseUseCase
from common.config import REPOS_DIR

logger = logging.getLogger(__name__)

_EXPLORE_USER_PREFIX = (
    "Ты отвечаешь редактору или обычному пользователю, который НЕ разбирается в коде. "
    "Объясняй на уровне интерфейса: что нажать, куда зайти, что должно произойти. "
    "Не показывай код, не упоминай технические детали. Кратко, для Telegram. "
    "Используй только чтение файлов — ничего не меняй.\n\n"
)

_EXPLORE_EXPERT_PREFIX = (
    "Ты отвечаешь техническому специалисту. "
    "Отвечай кратко и по делу, как для Telegram-сообщения. "
    "Показывай код, пути к файлам, конкретные решения. "
    "Используй только чтение файлов — ничего не меняй.\n\n"
)

_CHANGES_PREFIX = (
    "Ты — агент для внесения изменений в код. "
    "Предложи конкретные правки с путями к файлам и diff-ами. "
    "Кратко, для Telegram.\n\n"
)

_TOOL_LABELS = {
    "Read": "Читаю",
    "Grep": "Ищу",
    "Glob": "Ищу файлы",
    "Edit": "Редактирую",
    "Write": "Пишу",
    "Bash": "Выполняю",
    "WebFetch": "Загружаю",
    "WebSearch": "Ищу в интернете",
}

_UPDATE_INTERVAL = 2.5  # seconds between Telegram message updates


@dataclass
class CodeResult:
    text: str
    session_id: str | None = None


_retriever = None


def _set_retriever(r) -> None:
    global _retriever
    _retriever = r


def _write_claude_md() -> None:
    """Write CLAUDE.md from DB knowledge (scope=code) into REPOS_DIR."""
    try:
        if _retriever is None:
            return
        context = _retriever.retrieve_full_scope("code")
        if context:
            Path(REPOS_DIR, "CLAUDE.md").write_text(context, encoding="utf-8")
    except Exception:
        logger.debug("Could not write CLAUDE.md from DB", exc_info=True)


def _format_tool_status(name: str, tool_input: dict) -> str | None:
    """Build a human-readable status line from a tool_use event."""
    label = _TOOL_LABELS.get(name)
    if not label:
        return None
    if name == "Read":
        path = tool_input.get("file_path", "")
        short = Path(path).name if path else ""
        return f"{label} {short}" if short else label
    if name in ("Grep", "Glob"):
        pattern = tool_input.get("pattern", "")
        return f"{label}: {pattern}" if pattern else label
    if name in ("Edit", "Write"):
        path = tool_input.get("file_path", "")
        short = Path(path).name if path else ""
        return f"{label} {short}" if short else label
    if name == "Bash":
        cmd = tool_input.get("command", "")
        if len(cmd) > 60:
            cmd = cmd[:57] + "..."
        return f"{label}: {cmd}" if cmd else label
    return label


def _build_prompt(prompt: str, verbose: bool, expert: bool, mode: str) -> str:
    if verbose:
        return prompt
    if mode == "changes":
        return _CHANGES_PREFIX + prompt
    if expert:
        return _EXPLORE_EXPERT_PREFIX + prompt
    return _EXPLORE_USER_PREFIX + prompt


def run_claude_code(prompt: str, verbose: bool = False, expert: bool = False,
                    mode: str = "explore",
                    on_event: Callable[[str], None] | None = None,
                    resume_session_id: str | None = None) -> CodeResult:
    full_prompt = _build_prompt(prompt, verbose, expert, mode)
    _write_claude_md()

    if on_event:
        return _run_streaming(full_prompt, on_event, resume_session_id)
    return _run_simple(full_prompt, resume_session_id)


def _build_cmd(full_prompt: str, resume_session_id: str | None, extra_args: list[str] | None = None) -> list[str]:
    cmd = ["claude"]
    if resume_session_id:
        cmd += ["--resume", resume_session_id, "-p", full_prompt]
    else:
        cmd += ["-p", full_prompt]
    cmd += ["--max-turns", "5"]
    if extra_args:
        cmd += extra_args
    return cmd


def _run_simple(full_prompt: str, resume_session_id: str | None) -> CodeResult:
    try:
        result = subprocess.run(
            _build_cmd(full_prompt, resume_session_id),
            capture_output=True,
            text=True,
            cwd=REPOS_DIR,
            timeout=300,
        )
        if result.returncode != 0:
            logger.error("Claude Code exit=%d stdout=%s stderr=%s",
                         result.returncode, result.stdout[:500], result.stderr[:500])
        output = result.stdout.strip()
        if not output and result.stderr.strip():
            output = f"stderr: {result.stderr.strip()}"
        if not output:
            output = "(пустой ответ от Claude Code)"
        return CodeResult(text=output)
    except subprocess.TimeoutExpired:
        return CodeResult(text="Таймаут: Claude Code не ответил за 5 минут.")
    except FileNotFoundError:
        return CodeResult(text="Claude Code CLI не найден. Убедитесь, что он установлен.")
    except Exception as e:
        logger.exception("Claude Code execution failed")
        return CodeResult(text=f"Ошибка выполнения: {e}")


def _run_streaming(full_prompt: str, on_event: Callable[[str], None],
                   resume_session_id: str | None) -> CodeResult:
    try:
        proc = subprocess.Popen(
            _build_cmd(full_prompt, resume_session_id,
                       ["--output-format", "stream-json", "--verbose"]),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=REPOS_DIR,
        )
    except FileNotFoundError:
        return CodeResult(text="Claude Code CLI не найден. Убедитесь, что он установлен.")

    last_update = 0.0
    final_text_parts: list[str] = []
    session_id: str | None = None
    pending_status: str | None = None

    def _flush_status(force: bool = False) -> None:
        nonlocal pending_status, last_update
        if not pending_status:
            return
        now = time.monotonic()
        if force or (now - last_update) >= _UPDATE_INTERVAL:
            on_event(pending_status)
            last_update = now
            pending_status = None

    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            etype = event.get("type")

            if etype == "system" and event.get("subtype") == "init":
                session_id = event.get("session_id")

            elif etype == "assistant":
                content = event.get("message", {}).get("content", [])
                for block in content:
                    if block.get("type") == "tool_use":
                        status = _format_tool_status(block.get("name", ""), block.get("input", {}))
                        if status:
                            pending_status = status
                            _flush_status()
                    elif block.get("type") == "text":
                        text = block.get("text", "")
                        if text:
                            final_text_parts.append(text)

            elif etype == "result":
                result_text = event.get("result", "")
                sid = event.get("session_id") or session_id
                if result_text:
                    return CodeResult(text=result_text, session_id=sid)

        proc.wait(timeout=300)
    except subprocess.TimeoutExpired:
        proc.kill()
        return CodeResult(text="Таймаут: Claude Code не ответил за 5 минут.", session_id=session_id)
    except Exception as e:
        logger.exception("Claude Code streaming failed")
        proc.kill()
        return CodeResult(text=f"Ошибка выполнения: {e}", session_id=session_id)

    if final_text_parts:
        return CodeResult(text="\n".join(final_text_parts), session_id=session_id)

    stderr = proc.stderr.read() if proc.stderr else ""
    if stderr.strip():
        return CodeResult(text=f"stderr: {stderr.strip()}", session_id=session_id)
    return CodeResult(text="(пустой ответ от Claude Code)", session_id=session_id)


class RunClaudeCodeUseCase(BaseUseCase):
    def execute(self, prepared: Any, env: dict, user: dict) -> Any:
        return run_claude_code(**prepared)
