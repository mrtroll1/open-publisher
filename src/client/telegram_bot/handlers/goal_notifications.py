"""Goal notification background task."""

from __future__ import annotations

import asyncio
import logging
import os

from telegram_bot import backend_client
from telegram_bot.bot_helpers import bot, get_admin_ids

logger = logging.getLogger(__name__)

__all__ = ["goal_notification_task"]

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


async def goal_notification_task() -> None:
    """Background task: poll for goal notifications, send to admin."""
    admin_ids = get_admin_ids()
    if not admin_ids:
        logger.warning("No admin IDs configured, goal notifications disabled")
        return
    admin_id = next(iter(admin_ids))
    poll_interval = int(os.getenv("GOAL_NOTIFICATION_INTERVAL", "300"))
    logger.info("Goal notification listener started (poll every %ds)", poll_interval)
    while True:
        try:
            items = await backend_client.get_pending_notifications()
            for n in items:
                text = _format_notification(n)
                await bot.send_message(admin_id, text)
        except Exception as e:
            logger.exception("Goal notification error: %s", e)
        await asyncio.sleep(poll_interval)
