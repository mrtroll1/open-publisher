"""Response builders for interact handlers."""

import base64


def msg(text: str = "", *, keyboard=None, data=None) -> dict:
    m = {}
    if text:
        m["text"] = text
    if keyboard:
        m["keyboard"] = keyboard
    if data:
        m["data"] = data
    return m


def file_msg(pdf_bytes: bytes, filename: str, caption: str = "", *,
             data=None) -> dict:
    m = {
        "file_b64": base64.b64encode(pdf_bytes).decode(),
        "filename": filename,
    }
    if caption:
        m["text"] = caption
    if data:
        m["data"] = data
    return m


def side_msg(chat_id: int, text: str = "", *, pdf_bytes: bytes = None,
             filename: str = None, track: dict = None, data=None) -> dict:
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


def respond(messages=None, side_messages=None, fsm_state=_SENTINEL, fsm_data=None) -> dict:
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
