"""Conversation helpers — deterministic context building and formatting."""

from __future__ import annotations

from backend.infrastructure.repositories.postgres import DbGateway


def format_reply_chain(chain: list[dict]) -> str:
    parts = []
    for entry in chain:
        role = entry["role"]
        content = entry["content"]
        parts.append(f"{role}: {content}")
    return "\n".join(parts)


def build_conversation_context(
    chat_id: int,
    reply_message_id: int,
    reply_text: str,
    db: DbGateway,
    max_verbatim: int = 8,
) -> tuple[str, str | None]:
    """Look up conversation chain from DB; bootstrap from reply text if not found.

    Returns (history_str, parent_id).
    """
    conv_entry = db.get_conversation_by_message_id(chat_id, reply_message_id)

    if conv_entry:
        chain = db.get_reply_chain(conv_entry["id"], depth=20)
        if len(chain) > max_verbatim:
            skipped = len(chain) - max_verbatim
            chain = chain[-max_verbatim:]
            history = f"[{skipped} предыдущих сообщений опущено]\n" + format_reply_chain(chain)
        else:
            history = format_reply_chain(chain)
        return history, conv_entry["id"]

    history = f"assistant: {reply_text}"
    return history, None


