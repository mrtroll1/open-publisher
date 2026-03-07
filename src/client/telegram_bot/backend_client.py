"""Thin async HTTP client wrapping all backend API endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable

import httpx

from telegram_bot.config import BACKEND_URL

logger = logging.getLogger(__name__)

_client = httpx.AsyncClient(base_url=BACKEND_URL, timeout=300.0)

_MAX_RETRIES = 12
_RETRY_DELAY = 5  # seconds


async def _request_with_retry(method: str, url: str, **kwargs) -> httpx.Response:
    """Retry requests on connection errors (API restart / not yet up)."""
    for attempt in range(_MAX_RETRIES):
        try:
            return await _client.request(method, url, **kwargs)
        except (httpx.ConnectError, httpx.RemoteProtocolError):
            if attempt == _MAX_RETRIES - 1:
                raise
            logger.warning("API unavailable, retrying in %ds (%d/%d)", _RETRY_DELAY, attempt + 1, _MAX_RETRIES)
            await asyncio.sleep(_RETRY_DELAY)
    return None


async def _read_sse(resp, on_progress: Callable | None = None) -> dict | None:
    """Read SSE events from a streaming response."""
    resp.raise_for_status()
    result = None
    event_type = None
    async for line in resp.aiter_lines():
        if line.startswith("event: "):
            event_type = line[7:]
        elif line.startswith("data: "):
            data = json.loads(line[6:])
            if event_type == "progress" and on_progress:
                ret = on_progress(data["stage"], data["detail"])
                if asyncio.iscoroutine(ret):
                    await ret
            elif event_type == "done":
                if data.get("error"):
                    raise BackendError(data["error"])
                result = data["result"]
    return result


async def _stream_with_retry(method: str, url: str, on_progress: Callable | None = None, **kwargs) -> dict | None:
    """Stream request with retry on connection errors."""
    for attempt in range(_MAX_RETRIES):
        try:
            async with _client.stream(method, url, **kwargs) as resp:
                return await _read_sse(resp, on_progress)
        except (httpx.ConnectError, httpx.RemoteProtocolError):
            if attempt == _MAX_RETRIES - 1:
                raise
            logger.warning("API unavailable (stream), retrying in %ds (%d/%d)", _RETRY_DELAY, attempt + 1, _MAX_RETRIES)
            await asyncio.sleep(_RETRY_DELAY)
    return None


class BackendError(Exception):
    pass


def _unwrap(resp: httpx.Response) -> dict | str | list | None:
    resp.raise_for_status()
    data = resp.json()
    if data.get("error"):
        raise BackendError(data["error"])
    return data["result"]


# --- Interact ---

async def interact(action: str, payload: dict | None = None, context: dict | None = None) -> dict:
    resp = await _request_with_retry("POST","/interact", json={
        "action": action, "payload": payload or {}, "context": context or {},
    })
    return _unwrap(resp)


async def interact_stream(
    action: str,
    payload: dict | None = None,
    context: dict | None = None,
    on_progress: Callable[[str, str], None] | None = None,
) -> dict:
    """Call /interact/stream SSE endpoint. on_progress can be sync or async."""
    body = {"action": action, "payload": payload or {}, "context": context or {}}
    return await _stream_with_retry("POST", "/interact/stream", on_progress=on_progress, json=body)


# --- Brain ---

async def process(input: str, environment_id: str, user_id: str, *,  # noqa: PLR0913
                  chat_id: int | None = None,
                  reply_to_message_id: int | None = None,
                  reply_to_text: str = "") -> dict:
    payload = {
        "input": input, "environment_id": environment_id, "user_id": user_id,
    }
    if chat_id is not None:
        payload["chat_id"] = chat_id
    if reply_to_message_id is not None:
        payload["reply_to_message_id"] = reply_to_message_id
        payload["reply_to_text"] = reply_to_text
    resp = await _request_with_retry("POST","/brain/process", json=payload)
    return _unwrap(resp)


async def process_stream(  # noqa: PLR0913
    input: str, environment_id: str, user_id: str, *,
    chat_id: int | None = None,
    reply_to_message_id: int | None = None,
    reply_to_text: str = "",
    on_progress: Callable[[str, str], None] | None = None,
) -> dict:
    """Call /brain/process/stream SSE endpoint. on_progress can be sync or async."""
    payload = {
        "input": input, "environment_id": environment_id, "user_id": user_id,
    }
    if chat_id is not None:
        payload["chat_id"] = chat_id
    if reply_to_message_id is not None:
        payload["reply_to_message_id"] = reply_to_message_id
        payload["reply_to_text"] = reply_to_text
    return await _stream_with_retry("POST", "/brain/process/stream", on_progress=on_progress, json=payload)


async def command(cmd: str, args: str, environment_id: str, user_id: str) -> dict:
    resp = await _request_with_retry("POST","/brain/command", json={
        "command": cmd, "args": args,
        "environment_id": environment_id, "user_id": user_id,
    })
    return _unwrap(resp)


# --- Inbox ---

async def approve_support(uid: str):
    resp = await _request_with_retry("POST","/inbox/approve-support", json={"uid": uid})
    return _unwrap(resp)


async def skip_support(uid: str):
    resp = await _request_with_retry("POST","/inbox/skip-support", json={"uid": uid})
    return _unwrap(resp)


async def approve_editorial(uid: str):
    resp = await _request_with_retry("POST","/inbox/approve-editorial", json={"uid": uid})
    return _unwrap(resp)


async def skip_editorial(uid: str):
    resp = await _request_with_retry("POST","/inbox/skip-editorial", json={"uid": uid})
    return _unwrap(resp)


async def fetch_unread():
    resp = await _request_with_retry("POST","/inbox/fetch-unread")
    return _unwrap(resp)


async def get_pending_support(uid: str) -> dict | None:
    resp = await _request_with_retry("GET",f"/inbox/pending-support/{uid}")
    return _unwrap(resp)


async def get_pending_editorial(uid: str) -> dict | None:
    resp = await _request_with_retry("GET",f"/inbox/pending-editorial/{uid}")
    return _unwrap(resp)


async def update_and_approve_support(uid: str, text: str):
    resp = await _request_with_retry("POST","/inbox/update-and-approve-support", json={
        "uid": uid, "text": text,
    })
    return _unwrap(resp)


# --- Memory ---

async def teach(text: str, context: str = "") -> dict:
    resp = await _request_with_retry("POST","/memory/teach", json={
        "text": text, "context": context,
    })
    return _unwrap(resp)


async def memory_search(query: str, domain: str | None = None):
    params = {"query": query}
    if domain:
        params["domain"] = domain
    resp = await _request_with_retry("GET","/memory/search", params=params)
    return _unwrap(resp)


async def memory_list(domain: str | None = None, tier: str | None = None):
    params = {}
    if domain:
        params["domain"] = domain
    if tier:
        params["tier"] = tier
    resp = await _request_with_retry("GET","/memory/list", params=params)
    return _unwrap(resp)


async def get_entry(entry_id: str):
    resp = await _request_with_retry("GET",f"/memory/entry/{entry_id}")
    return _unwrap(resp)


async def update_entry(entry_id: str, content: str):
    resp = await _request_with_retry("PUT",f"/memory/entry/{entry_id}", json={"content": content})
    return _unwrap(resp)


async def delete_entry(entry_id: str):
    resp = await _request_with_retry("DELETE",f"/memory/entry/{entry_id}")
    return _unwrap(resp)


async def list_domains():
    resp = await _request_with_retry("GET","/memory/domains")
    return _unwrap(resp)


async def list_environments():
    resp = await _request_with_retry("GET","/memory/environments")
    return _unwrap(resp)


async def get_environment(chat_id: int = 0, name: str = "") -> dict | None:
    params = {}
    if chat_id:
        params["chat_id"] = chat_id
    if name:
        params["name"] = name
    resp = await _request_with_retry("GET","/memory/environment", params=params)
    return _unwrap(resp)


async def create_environment(name: str, description: str, system_context: str = ""):
    resp = await _request_with_retry("POST","/memory/environment/create", json={
        "name": name, "description": description, "system_context": system_context,
    })
    return _unwrap(resp)


async def update_environment(name: str, **kwargs):
    payload = {"name": name, **kwargs}
    resp = await _request_with_retry("PUT","/memory/environment/update", json=payload)
    return _unwrap(resp)


async def bind_environment(chat_id: int, name: str):
    resp = await _request_with_retry("POST","/memory/environment/bind", json={
        "chat_id": chat_id, "name": name,
    })
    return _unwrap(resp)


async def unbind_environment(chat_id: int):
    resp = await _request_with_retry("POST","/memory/environment/unbind", params={"chat_id": chat_id})
    return _unwrap(resp)


async def get_bindings(name: str) -> list:
    resp = await _request_with_retry("GET","/memory/environment/bindings", params={"name": name})
    return _unwrap(resp)


# --- User ---

async def get_admin_telegram_ids() -> list[int]:
    resp = await _request_with_retry("GET","/user/admin_telegram_ids")
    return _unwrap(resp) or []


async def is_admin(telegram_id: int) -> bool:
    resp = await _request_with_retry("GET","/user/is_admin", params={"telegram_id": telegram_id})
    return _unwrap(resp) or False


async def get_user_context(telegram_id: int | str) -> str:
    resp = await _request_with_retry("GET","/user/context", params={"telegram_id": int(telegram_id)})
    return _unwrap(resp) or ""


async def add_user_note(user_id: str, text: str, domain: str = "general"):
    resp = await _request_with_retry("POST",f"/user/{user_id}/note", json={
        "text": text, "domain": domain,
    })
    return _unwrap(resp)


# --- Messages ---

async def save_message(text: str, *, environment: str | None = None,  # noqa: PLR0913
                       chat_id: int | None = None, type: str = "user",
                       user_id: str | None = None, parent_id: str | None = None,
                       metadata: dict | None = None) -> str:
    resp = await _request_with_retry("POST","/message/save", json={
        "text": text, "environment": environment,
        "chat_id": chat_id, "type": type,
        "user_id": user_id, "parent_id": parent_id,
        "metadata": metadata,
    })
    return _unwrap(resp)["id"]


async def get_message_by_telegram_id(chat_id: int, telegram_message_id: int) -> dict | None:
    resp = await _request_with_retry("GET","/message/by-telegram-id", params={
        "chat_id": chat_id, "telegram_message_id": telegram_message_id,
    })
    return _unwrap(resp)


async def update_message_metadata(message_id: str, updates: dict):
    resp = await _request_with_retry("PUT",f"/message/{message_id}/metadata", json={
        "updates": updates,
    })
    return _unwrap(resp)


async def store_feedback(text: str, domain: str):
    resp = await _request_with_retry("POST","/admin/store-feedback", json={
        "text": text, "domain": domain,
    })
    return _unwrap(resp)
