"""Conversation controller — NL conversation with RAG context."""

from __future__ import annotations

from typing import Any

from backend.brain.base_controller import BaseController
from backend.infrastructure.repositories.postgres import DbGateway


def _format_reply_chain(chain: list[dict]) -> str:
    parts = []
    for entry in chain:
        parts.append(f"{entry['role']}: {entry['content']}")
    return "\n".join(parts)


def _build_conversation_context(
    chat_id: int, reply_message_id: int, reply_text: str,
    db: DbGateway, max_verbatim: int = 8,
) -> tuple[str, str | None]:
    conv_entry = db.get_conversation_by_message_id(chat_id, reply_message_id)
    if conv_entry:
        chain = db.get_reply_chain(conv_entry["id"], depth=20)
        if len(chain) > max_verbatim:
            skipped = len(chain) - max_verbatim
            chain = chain[-max_verbatim:]
            history = f"[{skipped} предыдущих сообщений опущено]\n" + _format_reply_chain(chain)
        else:
            history = _format_reply_chain(chain)
        return history, conv_entry["id"]
    return f"assistant: {reply_text}", None


class ConversationController(BaseController):
    """NL conversation with reply chain history and user context."""

    def __init__(self, conversation_reply, db: DbGateway, retriever):
        self._reply = conversation_reply
        self._db = db
        self._retriever = retriever

    def execute(self, input: str, env: dict, user: dict, **kwargs) -> Any:
        history = ""
        parent_id = None

        chat_id = kwargs.get("chat_id")
        reply_to_message_id = kwargs.get("reply_to_message_id")
        reply_to_text = kwargs.get("reply_to_text", "")

        if chat_id and reply_to_message_id:
            history, parent_id = _build_conversation_context(
                chat_id, reply_to_message_id, reply_to_text, self._db,
            )

        user_context = ""
        if user:
            user_context = self._retriever.get_user_context(user["id"]) if user.get("id") else ""

        context = {
            "environment": env.get("system_context", ""),
            "allowed_domains": env.get("allowed_domains"),
            "user_context": user_context,
            "conversation_history": history,
        }

        result = self._reply.run(input, context)
        result["parent_id"] = parent_id
        return result
