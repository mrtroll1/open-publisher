"""Run Claude Code CLI as a subprocess."""

from __future__ import annotations

import logging
import subprocess

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


def run_claude_code(prompt: str, verbose: bool = False, expert: bool = False,
                    mode: str = "explore") -> str:
    if verbose:
        full_prompt = prompt
    elif mode == "changes":
        full_prompt = _CHANGES_PREFIX + prompt
    elif expert:
        full_prompt = _EXPLORE_EXPERT_PREFIX + prompt
    else:
        full_prompt = _EXPLORE_USER_PREFIX + prompt
    try:
        result = subprocess.run(
            ["claude", "-p", full_prompt, "--max-turns", "5"],
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
