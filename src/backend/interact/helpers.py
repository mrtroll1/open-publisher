"""Response builders and shared helpers for interact handlers."""

from __future__ import annotations

import base64
from datetime import date
from typing import TypedDict

from backend.models import Contractor, RoleCode


class Payload(TypedDict, total=False):
    """Inbound data from the bot. Keys vary by action."""
    text: str
    file_b64: str
    filename: str
    mime: str
    callback_data: str
    rate: str
    contractor_id: str
    contractor_telegram: str


class InteractContext(TypedDict, total=False):
    """Session context passed by the bot alongside each request."""
    user_id: int
    is_admin: bool
    admin_ids: list[int]
    fsm_state: str | None
    fsm_data: dict


ROLE_LABELS = {
    RoleCode.AUTHOR: "автор",
    RoleCode.REDAKTOR: "редактор",
    RoleCode.KORREKTOR: "корректор",
}


def prev_month() -> str:
    today = date.today()
    if today.month == 1:
        return f"{today.year - 1}-12"
    return f"{today.year}-{today.month - 1:02d}"


def invoice_admin_data(contractor: Contractor, month: str, amount: int) -> dict:
    return {
        "type": "invoice_admin_caption",
        "name": contractor.display_name,
        "contractor_type": contractor.type.value,
        "month": month,
        "amount": int(amount),
    }


def msg(text: str = "", *, keyboard: list | None = None, data: dict | None = None) -> dict:
    m = {}
    if text:
        m["text"] = text
    if keyboard:
        m["keyboard"] = keyboard
    if data:
        m["data"] = data
    return m


def file_msg(pdf_bytes: bytes, filename: str, caption: str = "", *,
             data: dict | None = None) -> dict:
    m = {
        "file_b64": base64.b64encode(pdf_bytes).decode(),
        "filename": filename,
    }
    if caption:
        m["text"] = caption
    if data:
        m["data"] = data
    return m


def side_msg(chat_id: int, text: str = "", *, pdf_bytes: bytes | None = None,
             filename: str | None = None, track: dict | None = None,
             data: dict | None = None) -> dict:
    sm = {"chat_id": chat_id}
    if text:
        sm["text"] = text
    if data:
        sm["data"] = data
    if pdf_bytes:
        sm["file_b64"] = base64.b64encode(pdf_bytes).decode()
        sm["filename"] = filename
    if track:
        sm["track"] = track
    return sm


_SENTINEL = object()


def respond(messages: list[dict] | None = None, side_messages: list[dict] | None = None,
            fsm_state: str | None = _SENTINEL, fsm_data: dict | None = None) -> dict:
    """Build response dict.

    fsm_state: string = set state, None = clear state, omitted = keep current.
    """
    r = {"messages": messages or []}
    if side_messages:
        r["side_messages"] = side_messages
    if fsm_state is not _SENTINEL:
        r["fsm_state"] = fsm_state
    if fsm_data is not None:
        r["fsm_data"] = fsm_data
    return r
