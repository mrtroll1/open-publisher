"""Tech support — deterministic thread management, formatting, save/discard."""

from __future__ import annotations

import uuid

from common.models import IncomingEmail, SupportDraft


def format_thread(history: list[dict]) -> str:
    lines = ["## История переписки"]
    for msg in history:
        direction = "<<< входящее" if msg["direction"] == "inbound" else ">>> исходящее"
        lines.append(f"\n[{direction}] От: {msg['from_addr']} | {msg['date']}")
        lines.append(f"Тема: {msg['subject']}")
        lines.append(msg["body"] or "")
    return "\n".join(lines)


def build_thread_message(draft: SupportDraft, tag: str) -> IncomingEmail:
    em = draft.email
    return IncomingEmail(
        uid="",
        from_addr=em.to_addr,
        to_addr=em.reply_to or em.from_addr,
        subject=em.subject,
        body=draft.draft_reply,
        date="",
        message_id=f"<{tag}>",
        in_reply_to=em.message_id,
    )


def save_outbound(uid: str, draft: SupportDraft, uid_thread: dict[str, str], db) -> None:
    """Save sent reply to thread history."""
    thread_id = uid_thread.pop(uid, None)
    if not thread_id:
        return
    msg = build_thread_message(draft, f"outbound-{uuid.uuid4().hex}")
    db.save_message(thread_id, msg, "outbound")


def discard(uid: str, draft: SupportDraft | None, uid_thread: dict[str, str], db) -> None:
    """Clean up thread tracking for a skipped email."""
    thread_id = uid_thread.pop(uid, None)
    if draft and thread_id:
        msg = build_thread_message(draft, f"draft-rejected-{uuid.uuid4().hex}")
        db.save_message(thread_id, msg, "draft_rejected")


