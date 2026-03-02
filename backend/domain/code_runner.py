"""Run Claude Code CLI as a subprocess."""

from __future__ import annotations

import logging
import subprocess

from common.config import REPOS_DIR

logger = logging.getLogger(__name__)

_CONCISE_PREFIX = (
    "Ответь кратко и по делу, как для Telegram-сообщения. "
    "Не используй блоки кода длиннее ~20 строк. Фокусируйся на ключевой информации.\n\n"
)


def run_claude_code(prompt: str, verbose: bool = False) -> str:
    full_prompt = prompt if verbose else _CONCISE_PREFIX + prompt
    try:
        result = subprocess.run(
            ["claude", "-p", full_prompt, "--max-turns", "5"],
            capture_output=True,
            text=True,
            cwd=REPOS_DIR,
            timeout=300,
        )
        output = result.stdout.strip()
        if not output and result.stderr.strip():
            output = f"stderr: {result.stderr.strip()}"
        if not output:
            output = "(пустой ответ от Claude Code)"
        if len(output) > 4000:
            output = output[:4000] + "..."
        return output
    except subprocess.TimeoutExpired:
        return "Таймаут: Claude Code не ответил за 5 минут."
    except FileNotFoundError:
        return "Claude Code CLI не найден. Убедитесь, что он установлен."
    except Exception as e:
        logger.exception("Claude Code execution failed")
        return f"Ошибка выполнения: {e}"
