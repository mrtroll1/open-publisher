"""Goal notification background task."""

from __future__ import annotations

import asyncio
import logging
import os

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from telegram_bot import backend_client
from telegram_bot.bot_helpers import bot, get_admin_ids

logger = logging.getLogger(__name__)

__all__ = ["checkpoint_callback", "goal_notification_task"]

_FORMATS = {
    "task_triggered": "⚡ Задача активирована: {task_title}\nПричина: {reason}",
    "task_overdue": "⏰ Задача просрочена: {task_title}\nДедлайн: {due_date}",
    "task_completed": "✅ Агент выполнил: {task_title}\nРезультат: {result}",
}


def _format_notification(n: dict) -> str:
    ntype = n.get("type", "")
    payload = n.get("payload", {})
    template = _FORMATS.get(ntype)
    if template:
        try:
            return template.format_map(payload)
        except KeyError:
            pass
    return f"📋 {ntype}: {payload}"


def _format_checkpoint(payload: dict) -> tuple[str, list[list[dict]]]:
    """Format checkpoint notification with action buttons."""
    text = (
        f"Checkpoint: {payload.get('task_title', '?')}\n\n"
        f"Предыдущая задача: {payload.get('prev_task_title', '?')}\n"
        f"Результат:\n{payload.get('prev_result', '(нет)')}\n\n"
        f"Что дальше: {payload.get('task_description') or payload.get('task_title', '?')}"
    )
    task_id = payload.get("task_id", "")
    keyboard = [
        [{"text": "Утвердить", "callback_data": f"chk:approve:{task_id}"}],
        [{"text": "Пропустить", "callback_data": f"chk:skip:{task_id}"}],
    ]
    return text, keyboard


async def checkpoint_callback(callback) -> None:
    """Handle checkpoint approve/skip buttons."""
    data = callback.data or ""
    if not data.startswith("chk:"):
        return
    parts = data.split(":", 2)
    if len(parts) < 3:
        await callback.answer("Неверные данные")
        return
    action, task_id = parts[1], parts[2]
    result = await backend_client.interact(
        "checkpoint_action",
        payload={"task_id": task_id, "action": action},
    )
    messages = result.get("messages", [])
    text = messages[0]["text"] if messages else "Готово"
    await callback.message.answer(text)
    await callback.answer()


async def goal_notification_task() -> None:
    """Background task: poll for goal notifications, send to admin."""
    admin_ids = get_admin_ids()
    if not admin_ids:
        logger.warning("No admin IDs configured, goal notifications disabled")
        return
    admin_id = next(iter(admin_ids))
    poll_interval = int(os.getenv("GOAL_NOTIFICATION_INTERVAL", ""))
    logger.info("Goal notification listener started (poll every %ds)", poll_interval)
    while True:
        try:
            items = await backend_client.get_pending_notifications()
            for n in items:
                if n.get("type") == "checkpoint_ready":
                    text, keyboard = _format_checkpoint(n.get("payload", {}))
                    markup = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text=btn["text"], callback_data=btn["callback_data"])
                         for btn in row]
                        for row in keyboard
                    ])
                    await bot.send_message(admin_id, text, reply_markup=markup)
                else:
                    text = _format_notification(n)
                    await bot.send_message(admin_id, text)
        except Exception as e:
            logger.exception("Goal notification error: %s", e)
        await asyncio.sleep(poll_interval)
