"""Admin draft-reply business logic.

Sync functions extracted from telegram_bot/handlers/admin_handlers.py.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_GREETING_PREFIXES = (
    "здравствуйте", "добрый день", "добрый вечер", "доброе утро",
    "hello", "dear", "привет", "уважаем", "hi,", "hi ",
)


def classify_draft_reply(reply_text: str) -> str:
    """Return 'replacement' if text starts with a greeting, else 'feedback'."""
    if reply_text.strip().lower().startswith(_GREETING_PREFIXES):
        return "replacement"
    return "feedback"


def store_admin_feedback(text: str, domain: str, retriever) -> None:
    """Store teaching feedback via retriever. Logs and swallows errors."""
    try:
        retriever.store_feedback(text, domain=domain)
    except Exception:
        logger.exception("Failed to store admin feedback")
